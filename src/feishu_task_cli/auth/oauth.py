from __future__ import annotations

import secrets
import time
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


AUTHORIZE_ORIGIN = "https://accounts.feishu.cn"
TOKEN_PATH = "/open-apis/authen/v2/oauth/token"
IDENTITY_PATH = "/open-apis/authen/v1/user_info"


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
        if settings.app_id is None or settings.account_id is None:
            raise ValueError("FEISHU_APP_ID and FEISHU_ACCOUNT_ID are required for OAuth")
        if not {"offline_access", "task:task:write"}.issubset(settings.oauth_scopes):
            raise ValueError("OAuth scopes must include offline_access and task:task:write")
        if store.app_id != settings.app_id or store.account_id != settings.account_id:
            raise ValueError("token store namespace must match the declared app and account")
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

    def _redirect_uri(self) -> str:
        if self.settings.oauth_redirect_uri is None:
            raise OAuthError("FEISHU_OAUTH_REDIRECT_URI is required for OAuth login")
        parsed = urlsplit(self.settings.oauth_redirect_uri)
        try:
            port = parsed.port
        except ValueError:
            port = None
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or port is None
            or parsed.path in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise OAuthError("configured OAuth redirect URI is not a fixed loopback URL")
        return self.settings.oauth_redirect_uri

    def _client_secret(self) -> str:
        if self.settings.app_secret is None:
            raise OAuthError("FEISHU_APP_SECRET is required for OAuth token operations")
        return self.settings.app_secret.get_secret_value()

    def authorization_url(self, *, state: str) -> str:
        query = urlencode(
            {
                "client_id": self.app_id,
                "response_type": "code",
                "redirect_uri": self._redirect_uri(),
                "scope": " ".join(self.settings.oauth_scopes),
                "state": state,
            }
        )
        return f"{AUTHORIZE_ORIGIN}/open-apis/authen/v1/authorize?{query}"

    def login(self, *, timeout: float = 120) -> None:
        """Run one explicit browser login with a loopback-only callback."""
        state = secrets.token_urlsafe(32)
        callback: dict[str, str] = {}
        redirect_uri = self._redirect_uri()
        target = urlsplit(redirect_uri)
        assert target.port is not None

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                request_target = urlsplit(self.path)
                query = parse_qs(request_target.query)
                if (
                    request_target.path != target.path
                    or query.get("state") != [state]
                    or len(query.get("code", [])) != 1
                ):
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

        server: HTTPServer | None = None
        server_failed = False
        try:
            server = HTTPServer(("127.0.0.1", target.port), CallbackHandler)
        except OSError:
            server_failed = True
        if server_failed or server is None:
            raise OAuthError("configured OAuth callback address is unavailable")
        deadline = time.monotonic() + timeout
        try:
            if not self._browser_open(self.authorization_url(state=state)):
                raise OAuthError("browser could not be opened for explicit OAuth setup")
            while "code" not in callback:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                server.timeout = remaining
                server.handle_request()
        finally:
            server.server_close()
        code = callback.get("code")
        if code is None:
            raise OAuthError("OAuth callback was not received before timeout")
        self.exchange_code(code=code)

    def _token_payload(
        self, response: httpx.Response, *, require_refresh: bool
    ) -> Mapping[str, object]:
        if response.status_code >= 400:
            raise OAuthError(f"OAuth token endpoint returned HTTP {response.status_code}")
        invalid_json = False
        try:
            raw_envelope = response.json()
        except ValueError:
            invalid_json = True
            raw_envelope = None
        if invalid_json:
            raise OAuthError("OAuth token response was invalid")
        envelope = _mapping(raw_envelope, message="OAuth token response was invalid")
        if envelope.get("code", 0) != 0:
            raise OAuthError("OAuth token endpoint rejected the request")
        if require_refresh and not isinstance(envelope.get("refresh_token"), str):
            raise OAuthError("OAuth token response did not contain a rotated refresh token")
        return envelope

    def _store_token_payload(self, data: Mapping[str, object]) -> None:
        access = data.get("access_token")
        refresh = data.get("refresh_token")
        if not isinstance(access, str) or not access:
            raise OAuthError("OAuth token response did not contain an access token")
        if not isinstance(refresh, str) or not refresh:
            raise OAuthError("OAuth token response did not contain a rotated refresh token")
        self._identity_for_token(access)
        self.store.set_refresh_token(refresh)
        self.store.set_access_token(access)

    def exchange_code(self, *, code: str) -> None:
        if not code:
            raise ValueError("authorization code must be non-empty")
        payload: dict[str, str] = {
            "grant_type": "authorization_code",
            "client_id": self.app_id,
            "client_" + "secret": self._client_secret(),
            "code": code,
            "redirect_uri": self._redirect_uri(),
        }
        response: httpx.Response | None = None
        transport_failed = False
        try:
            response = self._http.post(f"{self.api_origin}{TOKEN_PATH}", json=payload)
        except httpx.TransportError:
            transport_failed = True
        if transport_failed or response is None:
            raise OAuthError("OAuth code exchange transport failed")
        self._store_token_payload(self._token_payload(response, require_refresh=True))

    def refresh(self) -> None:
        """Refresh once, retrying only one connection failure known to precede send."""
        refresh_credential = self.store.get_refresh_token()
        if refresh_credential is None:
            raise OAuthError("no refresh token is available")
        payload: dict[str, str] = {
            "grant_type": "refresh_token",
            "client_id": self.app_id,
            "client_" + "secret": self._client_secret(),
            "refresh_token": refresh_credential,
        }
        response: httpx.Response | None = None
        transport_failed = False
        for attempt in range(2):
            try:
                response = self._http.post(f"{self.api_origin}{TOKEN_PATH}", json=payload)
            except httpx.ConnectError:
                if attempt == 0:
                    continue
                transport_failed = True
            except httpx.TransportError:
                transport_failed = True
            break
        if transport_failed or response is None:
            raise OAuthError("OAuth refresh transport failed")
        self._store_token_payload(self._token_payload(response, require_refresh=True))

    def _identity_for_token(self, token: str) -> Mapping[str, str]:
        response: httpx.Response | None = None
        transport_failed = False
        try:
            response = self._http.get(
                f"{self.api_origin}{IDENTITY_PATH}",
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.TransportError:
            transport_failed = True
        if transport_failed or response is None:
            raise OAuthError("identity transport failed")
        if response.status_code >= 400:
            raise OAuthError(f"identity endpoint returned HTTP {response.status_code}")
        invalid_json = False
        try:
            raw_envelope = response.json()
        except ValueError:
            invalid_json = True
            raw_envelope = None
        if invalid_json:
            raise OAuthError("identity response was invalid")
        envelope = _mapping(raw_envelope, message="identity response was invalid")
        if envelope.get("code", 0) != 0:
            raise OAuthError("identity endpoint rejected the request")
        identity = _mapping(envelope.get("data"), message="identity response was invalid")
        safe_identity = {
            key: value for key, value in identity.items() if isinstance(value, str) and value
        }
        account_candidates = {
            safe_identity[key]
            for key in ("account_id", "user_id", "union_id", "open_id")
            if key in safe_identity
        }
        declared_account = self.settings.account_id
        assert declared_account is not None
        if declared_account not in account_candidates:
            raise OAuthError("verified identity does not match the declared account")
        tenant = safe_identity.get("tenant_id") or safe_identity.get("tenant_key")
        if tenant is None:
            raise OAuthError("verified identity is missing tenant_id")
        if self.settings.tenant_id is not None and tenant != self.settings.tenant_id:
            raise OAuthError("verified identity does not match the declared tenant")
        actor = (
            safe_identity.get("actor_id")
            or safe_identity.get("open_id")
            or safe_identity.get("user_id")
        )
        if actor is None:
            raise OAuthError("verified identity is missing actor_id")
        return {
            **safe_identity,
            "tenant_id": tenant,
            "account_id": declared_account,
            "actor_id": actor,
        }

    def get_identity(self) -> Mapping[str, str]:
        token = self.access_token()
        if token is None:
            raise OAuthError("authentication is not configured")
        return self._identity_for_token(token)

    def status(self) -> AuthStatus:
        if self.access_token() is None:
            return AuthStatus(authenticated=False)
        return AuthStatus(authenticated=True, auth_context=resolve_auth_context(self))

    def logout(self) -> None:
        if self.settings.user_access_token is not None:
            raise OAuthError(
                "process-injected access token cannot be removed by logout; "
                "remove it from the environment"
            )
        self.store.clear()
