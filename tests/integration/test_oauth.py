from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import suppress
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from feishu_task_cli.auth.config import Settings
from feishu_task_cli.auth.keyring_store import TokenStore
from feishu_task_cli.auth.oauth import OAuthClient, OAuthDeniedError, OAuthError

TOKEN_FIXTURE = Path(__file__).parents[1] / "fixtures" / "feishu_oauth_v2_token.json"


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
        assert str(request.url) == "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
        assert json.loads(request.content)["code"] == "synthetic-code"
        return httpx.Response(200, json=json.loads(TOKEN_FIXTURE.read_text()))

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


def test_authorization_url_matches_current_official_contract() -> None:
    client = OAuthClient(settings=_settings(), store=_store())

    url = urllib.parse.urlsplit(
        client.authorization_url(
            redirect_uri="http://127.0.0.1:12345/callback",
            state="synthetic-state",
        )
    )
    query = urllib.parse.parse_qs(url.query)

    assert f"{url.scheme}://{url.netloc}{url.path}" == (
        "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
    )
    assert query["client_id"] == ["cli_synthetic"]
    assert "app_id" not in query
    assert "offline_access" in query["scope"][0].split()


def test_refresh_retries_one_confirmed_connect_error_and_stores_rotation() -> None:
    attempts = 0
    store = _store()
    store.set_refresh_token("synthetic-old-refresh")

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("synthetic connection failure", request=request)
        payload = json.loads(TOKEN_FIXTURE.read_text())
        payload["access_token"] = "synthetic-new-access"
        payload["refresh_token"] = "synthetic-new-refresh"
        assert str(request.url) == "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
        return httpx.Response(200, json=payload)

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
                    "union_id": "account_synthetic",
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
    assert "account_synthetic" not in rendered
    assert "actor_synthetic" not in rendered

    client.logout()
    assert store.get_access_token() is None
    assert store.get_refresh_token() is None


def test_oauth_client_rejects_mismatched_store_owners() -> None:
    with pytest.raises(ValueError, match="app owner"):
        OAuthClient(
            settings=_settings(),
            store=TokenStore(
                app_id="different-app",
                account_id="account_synthetic",
                backend=MemoryKeyring(),
            ),
        )
    with pytest.raises(ValueError, match="account owner"):
        OAuthClient(
            settings=_settings(),
            store=TokenStore(
                app_id="cli_synthetic",
                account_id="different-account",
                backend=MemoryKeyring(),
            ),
        )


def test_status_fails_closed_when_resolved_union_id_differs_from_store_owner() -> None:
    store = _store()
    store.set_access_token("synthetic-access")

    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "tenant_id": "tenant_synthetic",
                    "union_id": "different-account",
                    "open_id": "actor_synthetic",
                },
            },
        )

    client = OAuthClient(
        settings=_settings(),
        store=store,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )
    with pytest.raises(OAuthError, match="account identity did not match"):
        client.status()


def test_refresh_requires_rotated_refresh_token() -> None:
    store = _store()
    store.set_refresh_token("synthetic-old-refresh")

    def transport(request: httpx.Request) -> httpx.Response:
        payload = json.loads(TOKEN_FIXTURE.read_text())
        payload.pop("refresh_token")
        return httpx.Response(200, json=payload)

    client = OAuthClient(
        settings=_settings(),
        store=store,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )
    with pytest.raises(OAuthError, match="refresh token"):
        client.refresh()
    assert store.get_refresh_token() == "synthetic-old-refresh"


class FailAccessWriteKeyring(MemoryKeyring):
    def set_password(self, service: str, username: str, password: str) -> None:
        if username.endswith("-access") and password == "synthetic-new-access":
            raise RuntimeError("synthetic secret must not escape")
        super().set_password(service, username, password)


def test_refresh_second_token_write_failure_is_fail_closed_after_restart() -> None:
    backend = FailAccessWriteKeyring()
    store = TokenStore(app_id="cli_synthetic", account_id="account_synthetic", backend=backend)
    store.set_access_token("synthetic-old-access")
    store.set_refresh_token("synthetic-old-refresh")

    def transport(request: httpx.Request) -> httpx.Response:
        payload = json.loads(TOKEN_FIXTURE.read_text())
        payload["access_token"] = "synthetic-new-access"
        payload["refresh_token"] = "synthetic-new-refresh"
        return httpx.Response(200, json=payload)

    client = OAuthClient(
        settings=_settings(),
        store=store,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )
    with pytest.raises(Exception) as caught:
        client.refresh()
    assert "synthetic-new-access" not in repr(caught.value)

    restarted = TokenStore(app_id="cli_synthetic", account_id="account_synthetic", backend=backend)
    assert restarted.get_access_token() is None
    assert restarted.get_refresh_token() == "synthetic-new-refresh"


def test_callback_ignores_wrong_path_and_state_until_matching_callback() -> None:
    store = _store()

    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=json.loads(TOKEN_FIXTURE.read_text()))

    def browser_open(url: str) -> bool:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        callback = query["redirect_uri"][0]
        state = query["state"][0]

        def invoke() -> None:
            for noisy_url in (
                callback.replace("/callback", "/favicon.ico"),
                f"{callback}?code=noise&state=wrong-state",
            ):
                with suppress(urllib.error.HTTPError):
                    urllib.request.urlopen(noisy_url)
            with urllib.request.urlopen(f"{callback}?code=synthetic-code&state={state}"):
                pass

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


def test_matching_oauth_denial_raises_typed_error() -> None:
    def browser_open(url: str) -> bool:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        callback = query["redirect_uri"][0]
        state = query["state"][0]

        def invoke() -> None:
            with suppress(urllib.error.HTTPError):
                urllib.request.urlopen(
                    f"{callback}?error=access_denied&error_description=secret&state={state}"
                )

        threading.Thread(target=invoke).start()
        return True

    client = OAuthClient(settings=_settings(), store=_store(), browser_open=browser_open)
    with pytest.raises(OAuthDeniedError) as caught:
        client.login(timeout=2)
    assert "secret" not in repr(caught.value)
