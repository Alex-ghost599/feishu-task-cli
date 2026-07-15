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
        failed = False
        try:
            self.backend.set_password(SERVICE_NAME, self._username(kind), token)
        except Exception:
            failed = True
        if failed:
            raise TokenStoreError("keyring could not store authentication material")

    def _get(self, kind: str) -> str | None:
        failed = False
        result: str | None = None
        try:
            result = self.backend.get_password(SERVICE_NAME, self._username(kind))
        except Exception:
            failed = True
        if failed:
            raise TokenStoreError("keyring could not read authentication material")
        return result

    def set_access_token(self, token: str) -> None:
        self._set("access", token)

    def set_refresh_token(self, token: str) -> None:
        self._set("refresh", token)

    def get_access_token(self) -> str | None:
        return self._get("access")

    def get_refresh_token(self) -> str | None:
        return self._get("refresh")

    def clear(self) -> None:
        for kind in ("access", "refresh"):
            failed = False
            try:
                with suppress(PasswordDeleteError):
                    self.backend.delete_password(SERVICE_NAME, self._username(kind))
            except Exception:
                failed = True
            if failed:
                raise TokenStoreError("keyring could not clear authentication material")
