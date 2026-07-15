from __future__ import annotations

import hashlib
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Protocol

import keyring
from keyring.errors import PasswordDeleteError

SERVICE_NAME = "feishu-task-cli"


class TokenStoreError(RuntimeError):
    """A stable keyring failure that does not expose token material."""


class KeyringBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...


def _fingerprint(domain: str, value: str) -> str:
    if not value.strip():
        raise ValueError(f"{domain} must be a non-empty string")
    return hashlib.sha256(f"feishu-task-cli:keyring:{domain}\0{value}".encode()).hexdigest()


@dataclass(frozen=True)
class TokenStore:
    """Store OAuth tokens under non-identifying, domain-separated keyring names."""

    app_id: str = field(repr=False)
    account_id: str = field(repr=False)
    backend: KeyringBackend = field(default=keyring, repr=False, compare=False)

    def _username(self, kind: str) -> str:
        app = _fingerprint("app", self.app_id)
        account = _fingerprint("account", self.account_id)
        return f"app-{app}-account-{account}-{kind}"

    def _set(self, kind: str, token: str) -> None:
        if not token:
            raise ValueError("token must be non-empty")
        try:
            self.backend.set_password(SERVICE_NAME, self._username(kind), token)
        except Exception:
            raise TokenStoreError("keyring could not store authentication material") from None

    def _get(self, kind: str) -> str | None:
        try:
            return self.backend.get_password(SERVICE_NAME, self._username(kind))
        except Exception:
            raise TokenStoreError("keyring could not read authentication material") from None

    def _delete(self, kind: str) -> None:
        try:
            with suppress(PasswordDeleteError):
                self.backend.delete_password(SERVICE_NAME, self._username(kind))
        except Exception:
            raise TokenStoreError("keyring could not clear authentication material") from None

    def set_access_token(self, token: str) -> None:
        self._set("access", token)

    def set_refresh_token(self, token: str) -> None:
        self._set("refresh", token)

    def get_access_token(self) -> str | None:
        if self._get("transaction") is not None:
            return None
        return self._get("access")

    def get_refresh_token(self) -> str | None:
        return self._get("refresh")

    def commit_tokens(self, *, access_token: str, refresh_token: str) -> None:
        """Commit a rotated token pair while making interrupted state fail closed."""
        if not access_token or not refresh_token:
            raise ValueError("token pair must be non-empty")
        self._set("transaction", "pending-v1")
        self._set("refresh", refresh_token)
        self._delete("access")
        self._set("access", access_token)
        self._delete("transaction")

    def clear(self) -> None:
        for kind in ("access", "refresh", "transaction"):
            self._delete(kind)
