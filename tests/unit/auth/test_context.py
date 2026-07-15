from __future__ import annotations

import pytest

from feishu_task_cli.auth.context import build_auth_context, resolve_auth_context

ORIGIN = "https://open.feishu.cn"


def test_different_actor_changes_context() -> None:
    first = build_auth_context(
        api_origin=ORIGIN,
        app_id="cli_a",
        tenant_id="tenant_a",
        account_id="account_a",
        actor_id="actor_1",
    )
    second = build_auth_context(
        api_origin=ORIGIN,
        app_id="cli_a",
        tenant_id="tenant_a",
        account_id="account_a",
        actor_id="actor_2",
    )

    assert first.actor_fingerprint != second.actor_fingerprint
    assert first != second


def test_fingerprints_are_domain_separated_and_displays_are_safe() -> None:
    raw = "same-synthetic-identifier"
    context = build_auth_context(
        api_origin=ORIGIN,
        app_id=raw,
        tenant_id=raw,
        account_id=raw,
        actor_id=raw,
    )

    fingerprints = {
        context.app_id_fingerprint,
        context.tenant_fingerprint,
        context.account_fingerprint,
        context.actor_fingerprint,
    }
    assert len(fingerprints) == 4
    assert raw not in repr(context)
    assert raw not in str(context.model_dump(mode="json"))
    assert all(
        len(display) == 12
        for display in (
            context.app_id_display,
            context.tenant_display,
            context.account_display,
            context.actor_display,
        )
    )


class IdentityClient:
    api_origin = ORIGIN
    app_id = "cli_synthetic"

    def get_identity(self) -> dict[str, str]:
        return {
            "tenant_id": "tenant_synthetic",
            "union_id": "account_synthetic",
            "open_id": "actor_synthetic",
            "user_id": "synthetic-optional-user-id",
        }


def test_resolve_auth_context_uses_verified_identity() -> None:
    context = resolve_auth_context(IdentityClient())

    expected = build_auth_context(
        api_origin=ORIGIN,
        app_id="cli_synthetic",
        tenant_id="tenant_synthetic",
        account_id="account_synthetic",
        actor_id="actor_synthetic",
    )
    assert context == expected


def test_resolve_auth_context_requires_union_id_and_open_id() -> None:
    class MissingCanonicalIdentity(IdentityClient):
        def get_identity(self) -> dict[str, str]:
            return {
                "tenant_id": "tenant_synthetic",
                "user_id": "synthetic-optional-user-id",
            }

    with pytest.raises(ValueError, match="union_id"):
        resolve_auth_context(MissingCanonicalIdentity())


def test_invalid_auth_context_origin_does_not_echo_input() -> None:
    secret_origin = "https://synthetic-secret.example"

    with pytest.raises(ValueError) as caught:
        build_auth_context(
            api_origin=secret_origin,
            app_id="cli_synthetic",
            tenant_id="tenant_synthetic",
            account_id="account_synthetic",
            actor_id="actor_synthetic",
        )

    assert secret_origin not in repr(caught.value)
    assert secret_origin not in str(caught.value)
