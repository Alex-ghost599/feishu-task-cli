from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Protocol, cast

from feishu_task_cli.artifacts.plan import AuthContext


def _fingerprint(domain: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{domain} must be a non-empty string")
    payload = f"feishu-task-cli:auth-context:v1:{domain}\0{value}".encode()
    return hashlib.sha256(payload).hexdigest()


def build_auth_context(
    api_origin: str,
    app_id: str,
    tenant_id: str,
    account_id: str,
    actor_id: str,
) -> AuthContext:
    """Build a non-identifying AuthContext using field-domain-separated hashes."""
    app = _fingerprint("app-id", app_id)
    tenant = _fingerprint("tenant-id", tenant_id)
    account = _fingerprint("account-id", account_id)
    actor = _fingerprint("actor-id", actor_id)
    return AuthContext(
        api_origin=api_origin,
        app_id_fingerprint=app,
        tenant_fingerprint=tenant,
        account_fingerprint=account,
        acting_user_fingerprint=actor,
        app_id_display=app[:12],
        tenant_display=tenant[:12],
        account_display=account[:12],
        acting_user_display=actor[:12],
    )


class IdentityClient(Protocol):
    @property
    def api_origin(self) -> str: ...

    @property
    def app_id(self) -> str: ...

    def get_identity(self) -> Mapping[str, str]: ...


def _identity_value(identity: Mapping[str, object], *names: str) -> str:
    for name in names:
        value = identity.get(name)
        if isinstance(value, str) and value.strip():
            return value
    raise ValueError(f"verified identity is missing {names[0]}")


def resolve_auth_context(client: IdentityClient) -> AuthContext:
    """Resolve authoritative identity fields through an authenticated client."""
    identity = cast(Mapping[str, object], client.get_identity())
    return build_auth_context(
        api_origin=client.api_origin,
        app_id=client.app_id,
        tenant_id=_identity_value(identity, "tenant_id", "tenant_key"),
        account_id=_identity_value(identity, "account_id", "user_id", "union_id"),
        actor_id=_identity_value(identity, "actor_id", "open_id", "user_id"),
    )
