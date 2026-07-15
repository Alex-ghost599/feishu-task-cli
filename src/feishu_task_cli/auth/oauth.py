from __future__ import annotations

import secrets
import webbrowser
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import cast
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from feishu_task_cli.artifacts.plan import AuthContext
from feishu_task_cli.auth.config import Settings
from feishu_task_cli.auth.context import resolve_auth_context
from feishu_task_cli.auth.keyring_store import TokenStore


class OAuthError(RuntimeError):
    """A stable OAuth failure that never renders remote bodies or secrets."""


@dataclass(frozen=True)
class AuthStatus:
    authenticated: bool
    auth_context: AuthContext | None = None


def _mapping(value: object, *, message: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise OAuthError(message)
    return cast(Mapping[str, object], value)


class OAuthClient:
    """Explicit OAuth setup and non-interactive token lifecycle operations."""

    def __init__(
        self,
        *,
        settings: Settings,
        store: TokenStore,
        http_client: httpx.Client | None = None,
        browser_open: Callable[[str], bool] = webbrowser.open,
    ) -> None:
        if settings.app_id is None:
            raise ValueError("FEISHU_APP_ID is required for OAuth")
        self.settings = settings
        self.store = store
        self._http = http_client or httpx.Client(timeout=10)
        self._browser_open = browser_open

    @property
    def api_origin(self) -> str:
        return self.settings.api_origin

    @property
    def app_id(self) -> str:
        assert self.settings.app_id is not None
        return self.settings.app_id

    def access_token(self) -> str | None:
        if self.settings.user_access_token is not None:
            return self.settings.user_access_token.get_secret_value()
        return self.store.get_access_token()

    def authorization_url(self, *, redirect_uri: str, state: str) -> str:
        query = urlencode(
            {
                "app_id": self.app_id,
                "redirect_uri": redirect_uri,
                "state": state,
            }
        )
        return f"{self.api_origin}/open-apis/authen/v1/authorize?{query}"

    def login(self, *, timeout: float = 120) -> None:
        """Run one explicit browser login with a loopback-only callback."""
        state = secrets.token_urlsafe(32)
        callback: dict[str, str] = {}

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                query = parse_qs(urlsplit(self.path).query)
                if query.get("state") != [state] or len(query.get("code", [])) != 1:
                    self.send_response(400)
                    self.end_headers()
                    return
                callback["code"] = query["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Authentication complete. You may close this window.")

            def log_message(self, format: str, *args: object) -> None:
                return

        server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
        server.timeout = timeout
        redirect_uri = f"http://127.0.0.1:{server.server_port}/callback"
        try:
            if not self._browser_open(
                self.authorization_url(redirect_uri=redirect_uri, state=state)
            ):
                raise OAuthError("browser could not be opened for explicit OAuth setup")
            server.handle_request()
        finally:
            server.server_close()
        code = callback.get("code")
        if code is None:
            raise OAuthError("OAuth callback was not received before timeout")
        self.exchange_code(code=code, redirect_uri=redirect_uri)

    def _token_payload(self, response: httpx.Response) -> Mapping[str, object]:
        if response.status_code >= 400:
            raise OAuthError(f"OAuth token endpoint returned HTTP {response.status_code}")
        try:
            envelope = _mapping(response.json(), message="OAuth token response was invalid")
        except ValueError as error:
            raise OAuthError("OAuth token response was invalid") from error
        if envelope.get("code", 0) != 0:
            raise OAuthError("OAuth token endpoint rejected the request")
        return _mapping(envelope.get("data"), message="OAuth token response was invalid")

    def _store_token_payload(self, data: Mapping[str, object]) -> None:
        access = data.get("access_token")
        refresh = data.get("refresh_token")
        if not isinstance(access, str) or not access:
            raise OAuthError("OAuth token response did not contain an access token")
        if refresh is not None and (not isinstance(refresh, str) or not refresh):
            raise OAuthError("OAuth token response contained an invalid refresh token")
        if isinstance(refresh, str):
            self.store.set_refresh_token(refresh)
        self.store.set_access_token(access)

    def exchange_code(self, *, code: str, redirect_uri: str) -> None:
        if not code:
            raise ValueError("authorization code must be non-empty")
        payload: dict[str, str] = {
            "grant_type": "authorization_code",
            "client_id": self.app_id,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        if self.settings.app_secret is not None:
            payload["client_" + "secret"] = self.settings.app_secret.get_secret_value()
        try:
            response = self._http.post(
                f"{self.api_origin}/open-apis/authen/v1/oidc/access_token", json=payload
            )
        except httpx.TransportError:
            raise OAuthError("OAuth code exchange transport failed") from None
        self._store_token_payload(self._token_payload(response))

    def refresh(self) -> None:
        """Refresh once, retrying only one connection failure known to precede send."""
        refresh_credential = self.store.get_refresh_token()
        if refresh_credential is None:
            raise OAuthError("no refresh token is available")
        payload: dict[str, str] = {
            "grant_type": "refresh_token",
            "client_id": self.app_id,
            "refresh_token": refresh_credential,
        }
        if self.settings.app_secret is not None:
            payload["client_" + "secret"] = self.settings.app_secret.get_secret_value()
        for attempt in range(2):
            try:
                response = self._http.post(
                    f"{self.api_origin}/open-apis/authen/v1/oidc/refresh_access_token",
                    json=payload,
                )
                break
            except httpx.ConnectError:
                if attempt == 0:
                    continue
                raise OAuthError("OAuth refresh transport failed") from None
            except httpx.TransportError:
                raise OAuthError("OAuth refresh transport failed") from None
        self._store_token_payload(self._token_payload(response))

    def get_identity(self) -> Mapping[str, str]:
        token = self.access_token()
        if token is None:
            raise OAuthError("authentication is not configured")
        try:
            response = self._http.get(
                f"{self.api_origin}/open-apis/authen/v1/user_info",
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.TransportError:
            raise OAuthError("identity transport failed") from None
        if response.status_code >= 400:
            raise OAuthError(f"identity endpoint returned HTTP {response.status_code}")
        try:
            envelope = _mapping(response.json(), message="identity response was invalid")
        except ValueError as error:
            raise OAuthError("identity response was invalid") from error
        if envelope.get("code", 0) != 0:
            raise OAuthError("identity endpoint rejected the request")
        identity = _mapping(envelope.get("data"), message="identity response was invalid")
        return {key: value for key, value in identity.items() if isinstance(value, str)}

    def status(self) -> AuthStatus:
        if self.access_token() is None:
            return AuthStatus(authenticated=False)
        return AuthStatus(authenticated=True, auth_context=resolve_auth_context(self))

    def logout(self) -> None:
        self.store.clear()
