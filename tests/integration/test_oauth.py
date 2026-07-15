from __future__ import annotations

import json
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


def _settings(*, headless_token: str | None = None) -> Settings:
    return Settings(
        app_id="cli_synthetic",
        account_id="account_synthetic",
        app_secret=None,
        user_access_token=None if headless_token is None else SecretStr(headless_token),
    )


def _store() -> TokenStore:
    return TokenStore(
        app_id="cli_synthetic",
        account_id="account_synthetic",
        backend=MemoryKeyring(),
    )


def test_headless_environment_token_takes_precedence() -> None:
    client = OAuthClient(settings=_settings(headless_token="synthetic-headless"), store=_store())

    assert client.access_token() == "synthetic-headless"


def test_explicit_localhost_callback_exchanges_code_and_stores_tokens() -> None:
    store = _store()

    def transport(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/oidc/access_token")
        assert json.loads(request.content)["code"] == "synthetic-code"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "access_token": "synthetic-access",
                    "refresh_token": "synthetic-refresh",
                },
            },
        )

    def browser_open(url: str) -> bool:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        callback = query["redirect_uri"][0]
        state = query["state"][0]

        def invoke() -> None:
            with urllib.request.urlopen(
                f"{callback}?code=synthetic-code&state={urllib.parse.quote(state)}"
            ) as response:
                assert response.status == 200

        threading.Thread(target=invoke).start()
        return True

    client = OAuthClient(
        settings=_settings(),
        store=store,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
        browser_open=browser_open,
    )

    client.login(timeout=2)

    assert store.get_access_token() == "synthetic-access"
    assert store.get_refresh_token() == "synthetic-refresh"


def test_refresh_retries_one_confirmed_connect_error_and_stores_rotation() -> None:
    attempts = 0
    store = _store()
    store.set_refresh_token("synthetic-old-refresh")

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("synthetic connection failure", request=request)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "access_token": "synthetic-new-access",
                    "refresh_token": "synthetic-new-refresh",
                },
            },
        )

    client = OAuthClient(
        settings=_settings(),
        store=store,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )

    client.refresh()

    assert attempts == 2
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
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)


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
                    "tenant_id": "tenant_synthetic",
                    "account_id": "account_synthetic",
                    "actor_id": "actor_synthetic",
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
    assert "account_synthetic" not in rendered
    assert "actor_synthetic" not in rendered

    client.logout()
    assert store.get_access_token() is None
    assert store.get_refresh_token() is None
