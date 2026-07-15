from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from feishu_task_cli.artifacts.plan import Action, AuthContext, PlanV1, TaskTarget
from feishu_task_cli.artifacts.receipt import Outcome
from feishu_task_cli.artifacts.review import CheckedFact

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def auth_context(account_fingerprint: str = "3" * 64) -> AuthContext:
    return AuthContext(
        api_origin="https://open.feishu.cn",
        app_id_fingerprint="1" * 64,
        tenant_fingerprint="2" * 64,
        account_fingerprint=account_fingerprint,
        acting_user_fingerprint="4" * 64,
        app_id_display="1" * 12,
        tenant_display="2" * 12,
        account_display=account_fingerprint[:12],
        acting_user_display="4" * 12,
    )


def plan(context: AuthContext) -> PlanV1:
    return PlanV1(
        created_at=NOW,
        tool_version="0.0.0",
        plan_id="plan_example_001",
        action=Action.CREATE,
        target=TaskTarget(tasklist_guid="tasklist_example"),
        requested_fields={"summary": "Prepare a synthetic example"},
        auth_context=context,
        expires_at=NOW + timedelta(minutes=15),
    )


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        PlanV1.model_validate({**plan(auth_context()).model_dump(mode="json"), "surprise": True})


def test_non_utc_datetime_is_rejected() -> None:
    with pytest.raises(ValidationError, match="UTC"):
        PlanV1(
            created_at=datetime(2026, 1, 2, 3, 4, 5),
            tool_version="0.0.0",
            plan_id="plan_example_001",
            action=Action.CREATE,
            target=TaskTarget(tasklist_guid="tasklist_example"),
            requested_fields={},
            auth_context=auth_context(),
            expires_at=NOW + timedelta(minutes=15),
        )


def test_changed_auth_context_changes_plan_hash() -> None:
    assert plan(auth_context("3" * 64)).plan_hash != plan(auth_context("5" * 64)).plan_hash


def test_enum_values_are_stable() -> None:
    assert [item.value for item in Action] == ["create", "update", "assign", "complete"]
    assert [item.value for item in CheckedFact] == [
        "action_checked",
        "target_identity_checked",
        "assignees_checked",
        "schedule_checked",
        "auth_context_checked",
        "precondition_checked",
    ]
    assert [item.value for item in Outcome] == [
        "verified",
        "partial",
        "unknown",
        "failed",
        "rejected",
    ]
