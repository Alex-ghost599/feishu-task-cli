from __future__ import annotations

import json
import socket
import threading
import urllib.parse
import urllib.request

import httpx
import pytest
from pydantic import SecretStr

from feishu_task_cli.auth.config import Settings
from feishu_task_cli.auth.keyring_store import TokenStore
from feishu_task_cli.auth.oauth import OAuthClient, OAuthError


class MemoryKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


def _settings(
    *,
    headless_token: str | None = None,
    redirect_uri: str = "http://127.0.0.1:8765/callback",
    account_id: str = "synthetic_account",
) -> Settings:
    return Settings(
        app_id="cli_synthetic",
        account_id=account_id,
        oauth_redirect_uri=redirect_uri,
        app_secret=SecretStr("synthetic-app-credential"),
        user_access_token=None if headless_token is None else SecretStr(headless_token),
    )


def _store() -> TokenStore:
    return TokenStore(
        app_id="cli_synthetic",
        account_id="synthetic_account",
        backend=MemoryKeyring(),
    )


def _identity_response(*, account_id: str = "synthetic_account") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "data": {
                "tenant_key": "tenant_synthetic",
                "user_id": account_id,
                "open_id": "actor_synthetic",
            },
        },
    )


def _free_loopback_uri() -> str:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    return f"http://127.0.0.1:{port}/callback"


def test_headless_environment_token_takes_precedence() -> None:
    client = OAuthClient(settings=_settings(headless_token="synthetic-headless"), store=_store())

    assert client.access_token() == "synthetic-headless"


def test_authorization_url_matches_current_feishu_contract() -> None:
    client = OAuthClient(settings=_settings(), store=_store())

    url = urllib.parse.urlsplit(client.authorization_url(state="synthetic-state"))
    query = urllib.parse.parse_qs(url.query)

    assert (url.scheme, url.netloc, url.path) == (
        "https",
        "accounts.feishu.cn",
        "/open-apis/authen/v1/authorize",
    )
    assert query == {
        "client_id": ["cli_synthetic"],
        "redirect_uri": ["http://127.0.0.1:8765/callback"],
        "response_type": ["code"],
        "scope": ["offline_access task:task:write"],
        "state": ["synthetic-state"],
    }


def test_oauth_requires_task_write_scope_and_client_secret() -> None:
    with pytest.raises(ValueError, match="scopes"):
        OAuthClient(
            settings=Settings(
                app_id="cli_synthetic",
                account_id="synthetic_account",
                oauth_redirect_uri="http://127.0.0.1:8765/callback",
                oauth_scopes=("offline_access",),
            ),
            store=_store(),
        )

    client = OAuthClient(
        settings=Settings(
            app_id="cli_synthetic",
            account_id="synthetic_account",
            oauth_redirect_uri="http://127.0.0.1:8765/callback",
        ),
        store=_store(),
    )
    with pytest.raises(OAuthError, match="FEISHU_APP_SECRET"):
        client.exchange_code(code="synthetic-code")


def test_explicit_localhost_callback_exchanges_code_and_stores_tokens() -> None:
    store = _store()
    redirect_uri = _free_loopback_uri()

    def transport(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _identity_response()
        assert request.url.path == "/open-apis/authen/v2/oauth/token"
        assert json.loads(request.content) == {
            "grant_type": "authorization_code",
            "client_id": "cli_synthetic",
            "client_secret": "synthetic-app-credential",
            "code": "synthetic-code",
            "redirect_uri": redirect_uri,
        }
        return httpx.Response(
            200,
            json={
                "code": 0,
                "access_token": "synthetic-access",
                "refresh_token": "synthetic-refresh",
            },
        )

    def browser_open(url: str) -> bool:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        callback = query["redirect_uri"][0]
        state = query["state"][0]
        assert callback == redirect_uri
        assert query["client_id"] == ["cli_synthetic"]
        assert query["response_type"] == ["code"]
        assert "offline_access" in query["scope"][0].split()

        def invoke() -> None:
            with pytest.raises(urllib.error.HTTPError):
                urllib.request.urlopen(f"{callback}?code=wrong&state=wrong")
            with urllib.request.urlopen(
                f"{callback}?code=synthetic-code&state={urllib.parse.quote(state)}"
            ) as response:
                assert response.status == 200

        threading.Thread(target=invoke, daemon=True).start()
        return True

    client = OAuthClient(
        settings=_settings(redirect_uri=redirect_uri),
        store=store,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
        browser_open=browser_open,
    )

    client.login(timeout=2)

    assert store.get_access_token() == "synthetic-access"
    assert store.get_refresh_token() == "synthetic-refresh"


def test_refresh_retries_one_confirmed_connect_error_and_stores_rotation() -> None:
    post_attempts = 0
    store = _store()
    store.set_refresh_token("synthetic-old-refresh")

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal post_attempts
        if request.method == "GET":
            return _identity_response()
        post_attempts += 1
        assert request.url.path == "/open-apis/authen/v2/oauth/token"
        assert json.loads(request.content)["grant_type"] == "refresh_token"
        if post_attempts == 1:
            raise httpx.ConnectError("synthetic connection failure", request=request)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "access_token": "synthetic-new-access",
                "refresh_token": "synthetic-new-refresh",
            },
        )

    client = OAuthClient(
        settings=_settings(),
        store=store,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )

    client.refresh()

    assert post_attempts == 2
    assert store.get_refresh_token() == "synthetic-new-refresh"


def test_refresh_does_not_retry_read_timeout() -> None:
    attempts = 0
    store = _store()
    store.set_refresh_token("synthetic-refresh")

    secret = "synthetic-refresh"

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout(secret, request=request)

    client = OAuthClient(
        settings=_settings(),
        store=store,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )

    with pytest.raises(OAuthError) as caught:
        client.refresh()
    assert attempts == 1
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)


def test_refresh_requires_rotated_refresh_token() -> None:
    store = _store()
    store.set_refresh_token("synthetic-old-refresh")

    client = OAuthClient(
        settings=_settings(),
        store=store,
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"code": 0, "access_token": "synthetic-new-access"},
                )
            )
        ),
    )

    with pytest.raises(OAuthError, match="rotated refresh token"):
        client.refresh()
    assert store.get_refresh_token() == "synthetic-old-refresh"
    assert store.get_access_token() is None


def test_oauth_invalid_json_has_no_leaking_exception_chain() -> None:
    secret = "synthetic-remote-body-secret"
    client = OAuthClient(
        settings=_settings(),
        store=_store(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=f"{{invalid {secret}")
            )
        ),
    )

    with pytest.raises(OAuthError) as caught:
        client.exchange_code(code="synthetic-code")
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert secret not in str(caught.value)


def test_namespace_and_verified_identity_must_match_declared_account() -> None:
    with pytest.raises(ValueError, match="namespace"):
        OAuthClient(
            settings=_settings(),
            store=TokenStore(
                app_id="cli_other",
                account_id="synthetic_account",
                backend=MemoryKeyring(),
            ),
        )

    mismatched_store = _store()
    mismatched_store.set_access_token("synthetic-access")
    client = OAuthClient(
        settings=_settings(),
        store=mismatched_store,
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: _identity_response(account_id="account_other")
            )
        ),
    )
    with pytest.raises(OAuthError, match="identity does not match"):
        client.status()


def test_logout_rejects_process_injected_token() -> None:
    client = OAuthClient(settings=_settings(headless_token="synthetic-headless"), store=_store())

    with pytest.raises(OAuthError, match="process-injected"):
        client.logout()
    assert client.access_token() == "synthetic-headless"


def test_status_returns_only_safe_fingerprints_and_logout_clears_tokens() -> None:
    store = _store()
    store.set_access_token("synthetic-access")
    store.set_refresh_token("synthetic-refresh")

    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "tenant_key": "tenant_synthetic",
                    "user_id": "synthetic_account",
                    "open_id": "actor_synthetic",
                },
            },
        )

    client = OAuthClient(
        settings=_settings(),
        store=store,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )

    status = client.status()

    assert status.authenticated is True
    assert status.auth_context is not None
    rendered = repr(status)
    assert "tenant_synthetic" not in rendered
    assert "synthetic_account" not in rendered
    assert "actor_synthetic" not in rendered

    client.logout()
    assert store.get_access_token() is None
    assert store.get_refresh_token() is None
