from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from feishu_task_cli.application.policy_engine import (
    build_neutral_policy,
    validate_execution_review,
)
from feishu_task_cli.application.reviewer import build_review
from feishu_task_cli.artifacts.plan import (
    Action,
    AssigneeIdentifierType,
    AssigneeRef,
    AuthContext,
    PlanV1,
    TaskTarget,
)
from feishu_task_cli.artifacts.policy import PolicyV1
from feishu_task_cli.artifacts.receipt import DeclaredReviewRelationship
from feishu_task_cli.artifacts.review import CheckedFact, ReviewV1, ReviewVerdict
from feishu_task_cli.errors import PolicyRejectedError

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def plan() -> PlanV1:
    return PlanV1.build(
        created_at=NOW,
        tool_version="0.0.0",
        plan_id="plan_example_policy",
        action=Action.CREATE,
        target=TaskTarget(tasklist_guid="tasklist_example"),
        requested_fields={"summary": "Synthetic policy test"},
        auth_context=AuthContext(
            api_origin="https://open.feishu.cn",
            app_id_fingerprint="1" * 64,
            tenant_fingerprint="2" * 64,
            account_fingerprint="3" * 64,
            acting_user_fingerprint="4" * 64,
            app_id_display="1" * 12,
            tenant_display="2" * 12,
            account_display="3" * 12,
            acting_user_display="4" * 12,
        ),
        expires_at=NOW + timedelta(minutes=20),
    )


def policy(**overrides: object) -> PolicyV1:
    values: dict[str, object] = {"created_at": NOW, "tool_version": "0.0.0"}
    values.update(overrides)
    return PolicyV1.build(**values)


def review(**overrides: object) -> ReviewV1:
    values: dict[str, object] = {
        "plan": plan(),
        "reviewer_id": "agent-a",
        "verdict": ReviewVerdict.APPROVED,
        "checked_facts": (CheckedFact.ACTION,),
        "created_at": NOW,
        "expires_at": NOW + timedelta(minutes=10),
    }
    values.update(overrides)
    return build_review(**values)


def test_same_declared_identity_derives_self_reviewed() -> None:
    result = validate_execution_review(plan(), review(), policy(), "agent-a", now=NOW)
    assert result is DeclaredReviewRelationship.SELF_REVIEWED


def test_different_declared_identity_derives_independent_review() -> None:
    result = validate_execution_review(plan(), review(), policy(), "agent-b", now=NOW)
    assert result is DeclaredReviewRelationship.INDEPENDENTLY_REVIEWED


def test_neutral_policy_has_no_private_target_defaults() -> None:
    neutral = build_neutral_policy(created_at=NOW)
    assert neutral.require_independent_review is False
    assert set(neutral.approved_actions) == set(Action)
    assert neutral.required_checked_facts == {}


@pytest.mark.parametrize("executor_id", ["", "   "])
def test_executor_identity_is_required(executor_id: str) -> None:
    with pytest.raises(PolicyRejectedError, match="executor identity"):
        validate_execution_review(plan(), review(), policy(), executor_id, now=NOW)


def test_independent_policy_rejects_same_declared_identity() -> None:
    with pytest.raises(PolicyRejectedError, match="different declared identities"):
        validate_execution_review(
            plan(), review(), policy(require_independent_review=True), "agent-a", now=NOW
        )


def test_intended_executor_must_match() -> None:
    with pytest.raises(PolicyRejectedError, match="intended executor"):
        validate_execution_review(
            plan(), review(intended_executor_id="agent-b"), policy(), "agent-c", now=NOW
        )


def test_rejected_and_expired_reviews_are_blocked() -> None:
    with pytest.raises(PolicyRejectedError, match="approved"):
        validate_execution_review(
            plan(), review(verdict=ReviewVerdict.REJECTED), policy(), "agent-b", now=NOW
        )
    with pytest.raises(PolicyRejectedError, match="expired"):
        validate_execution_review(
            plan(), review(), policy(), "agent-b", now=NOW + timedelta(minutes=11)
        )


def test_review_must_bind_current_plan_hash_and_integrity() -> None:
    changed = plan().model_copy(update={"plan_hash": "9" * 64})
    with pytest.raises(PolicyRejectedError, match="plan hash"):
        validate_execution_review(changed, review(), policy(), "agent-b", now=NOW)


def test_policy_enforces_action_and_required_checked_facts() -> None:
    with pytest.raises(PolicyRejectedError, match="not approved"):
        validate_execution_review(
            plan(), review(), policy(approved_actions=(Action.UPDATE,)), "agent-b", now=NOW
        )


def test_policy_enforces_age_warning_and_assignee_constraints() -> None:
    old_plan = PlanV1.build(
        **plan().model_dump(mode="python", exclude={"plan_hash", "created_at", "expires_at"}),
        created_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=5),
    )
    old_plan_review = build_review(
        plan=old_plan,
        reviewer_id="agent-a",
        verdict=ReviewVerdict.APPROVED,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    with pytest.raises(PolicyRejectedError, match="plan age"):
        validate_execution_review(
            old_plan,
            old_plan_review,
            policy(max_plan_age_seconds=60),
            "agent-b",
            now=NOW,
        )

    old_review = build_review(
        plan=old_plan,
        reviewer_id="agent-a",
        verdict=ReviewVerdict.APPROVED,
        created_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=5),
    )
    with pytest.raises(PolicyRejectedError, match="review age"):
        validate_execution_review(
            old_plan,
            old_review,
            policy(max_review_age_seconds=60),
            "agent-b",
            now=NOW,
        )

    with pytest.raises(PolicyRejectedError, match="warnings"):
        validate_execution_review(
            plan(),
            review(warnings=("Synthetic warning",)),
            policy(reject_warnings=True),
            "agent-b",
            now=NOW,
        )

    assign_plan = PlanV1.build(
        created_at=NOW,
        tool_version="0.0.0",
        plan_id="plan_example_assign",
        action=Action.ASSIGN,
        target=TaskTarget(task_guid="task_example"),
        requested_fields={},
        assignees=(
            AssigneeRef(
                identifier_type=AssigneeIdentifierType.USER_ID,
                identifier="user_example",
            ),
        ),
        auth_context=plan().auth_context,
        expires_at=NOW + timedelta(minutes=20),
        observed_before={},
        precondition_fingerprint="5" * 64,
    )
    assign_review = build_review(
        plan=assign_plan,
        reviewer_id="agent-a",
        verdict=ReviewVerdict.APPROVED,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    with pytest.raises(PolicyRejectedError, match="assignee identifier"):
        validate_execution_review(
            assign_plan,
            assign_review,
            policy(allowed_assignee_identifier_types=(AssigneeIdentifierType.OPEN_ID,)),
            "agent-b",
            now=NOW,
        )
    with pytest.raises(PolicyRejectedError, match="checked facts"):
        validate_execution_review(
            plan(),
            review(),
            policy(required_checked_facts={Action.CREATE: (CheckedFact.AUTH_CONTEXT,)}),
            "agent-b",
            now=NOW,
        )


def test_unknown_checked_fact_is_rejected_by_artifact_schema() -> None:
    values = review().model_dump(mode="json", exclude={"review_hash"})
    values["checked_facts"] = ["invented_fact"]
    with pytest.raises(ValidationError, match="checked_facts"):
        ReviewV1.build(**values)
