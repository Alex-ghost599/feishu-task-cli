from __future__ import annotations

import re

import pytest

from feishu_task_cli.auth.keyring_store import TokenStore, TokenStoreError


class MemoryKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.calls: list[tuple[str, str]] = []

    def get_password(self, service: str, username: str) -> str | None:
        self.calls.append((service, username))
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.calls.append((service, username))
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.calls.append((service, username))
        self.values.pop((service, username), None)


class RejectingKeyring(MemoryKeyring):
    def set_password(self, service: str, username: str, password: str) -> None:
        raise RuntimeError(password)


class LeakingKeyring(MemoryKeyring):
    secret = "synthetic-keyring-secret"

    def get_password(self, service: str, username: str) -> str | None:
        raise RuntimeError(self.secret)

    def delete_password(self, service: str, username: str) -> None:
        raise RuntimeError(self.secret)


def test_token_store_uses_fixed_service_and_fingerprint_only_usernames() -> None:
    backend = MemoryKeyring()
    store = TokenStore(app_id="cli_synthetic", account_id="account_synthetic", backend=backend)

    store.set_access_token("synthetic-access")
    store.set_refresh_token("synthetic-refresh")

    assert {service for service, _ in backend.calls} == {"feishu-task-cli"}
    usernames = {username for _, username in backend.calls}
    assert all(
        re.fullmatch(r"app-[0-9a-f]{64}-account-[0-9a-f]{64}-(?:access|refresh)", item)
        for item in usernames
    )
    assert all("cli_synthetic" not in item for item in usernames)
    assert all("account_synthetic" not in item for item in usernames)


def test_token_store_round_trips_and_clears_tokens_without_repr_leakage() -> None:
    backend = MemoryKeyring()
    store = TokenStore(app_id="cli_synthetic", account_id="account_synthetic", backend=backend)

    store.set_access_token("synthetic-access")
    store.set_refresh_token("synthetic-refresh")

    assert store.get_access_token() == "synthetic-access"
    assert store.get_refresh_token() == "synthetic-refresh"
    assert "synthetic-access" not in repr(store)
    assert "synthetic-refresh" not in repr(store)

    store.clear()
    assert store.get_access_token() is None
    assert store.get_refresh_token() is None


def test_keyring_backend_error_does_not_expose_token() -> None:
    secret = "synthetic-backend-secret"
    store = TokenStore(
        app_id="cli_synthetic",
        account_id="account_synthetic",
        backend=RejectingKeyring(),
    )

    with pytest.raises(TokenStoreError) as caught:
        store.set_access_token(secret)

    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_keyring_read_and_delete_errors_do_not_expose_backend_content() -> None:
    backend = LeakingKeyring()
    store = TokenStore(
        app_id="cli_synthetic",
        account_id="account_synthetic",
        backend=backend,
    )

    with pytest.raises(TokenStoreError) as read_error:
        store.get_access_token()
    with pytest.raises(TokenStoreError) as delete_error:
        store.clear()

    assert backend.secret not in repr(read_error.value)
    assert backend.secret not in repr(delete_error.value)
    assert read_error.value.__context__ is None
    assert delete_error.value.__context__ is None
