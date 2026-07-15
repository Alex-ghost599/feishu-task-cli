from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from feishu_task_cli.application.policy_engine import (
    STRICT_REQUIRED_FACTS,
    build_neutral_policy,
    build_strict_policy,
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
from feishu_task_cli.artifacts.review import CheckedFact, ReviewVerdict
from feishu_task_cli.errors import ArtifactIntegrityError, PolicyRejectedError

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


def review(**overrides: object):
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


def test_builtin_neutral_policy_has_no_private_target_defaults() -> None:
    neutral = build_neutral_policy(created_at=NOW)

    assert neutral.require_independent_review is False
    assert set(neutral.approved_actions) == set(Action)
    assert neutral.required_checked_facts == {}


def test_builtin_strict_policy_requires_independent_action_specific_review() -> None:
    strict = build_strict_policy(created_at=NOW)

    assert strict.require_independent_review is True
    assert strict.reject_warnings is True
    assert set(strict.required_checked_facts) == set(Action)
    assert strict.required_checked_facts == STRICT_REQUIRED_FACTS
    with pytest.raises(PolicyRejectedError, match="checked facts"):
        validate_execution_review(plan(), review(), strict, "agent-b", now=NOW)

    checked = review(checked_facts=STRICT_REQUIRED_FACTS[Action.CREATE])
    assert (
        validate_execution_review(plan(), checked, strict, "agent-b", now=NOW)
        is DeclaredReviewRelationship.INDEPENDENTLY_REVIEWED
    )


def test_different_declared_identity_derives_independent_review() -> None:
    result = validate_execution_review(plan(), review(), policy(), "agent-b", now=NOW)
    assert result is DeclaredReviewRelationship.INDEPENDENTLY_REVIEWED


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


def test_rejected_or_expired_review_is_blocked() -> None:
    with pytest.raises(PolicyRejectedError, match="approved"):
        validate_execution_review(
            plan(), review(verdict=ReviewVerdict.REJECTED), policy(), "agent-b", now=NOW
        )
    with pytest.raises(PolicyRejectedError, match="expired"):
        validate_execution_review(
            plan(),
            review(
                created_at=NOW,
                expires_at=NOW + timedelta(minutes=5),
            ),
            policy(),
            "agent-b",
            now=NOW + timedelta(minutes=6),
        )


def test_review_must_bind_current_plan_hash() -> None:
    other = plan().model_copy(update={"plan_hash": "9" * 64})
    with pytest.raises(PolicyRejectedError, match="plan hash"):
        validate_execution_review(other, review(), policy(), "agent-b", now=NOW)


def test_reviewer_refuses_to_sign_an_in_memory_tampered_plan() -> None:
    tampered = plan().model_copy(update={"requested_fields": {"summary": "Tampered"}})

    with pytest.raises(ArtifactIntegrityError, match="plan hash"):
        build_review(
            tampered,
            reviewer_id="agent-a",
            verdict=ReviewVerdict.APPROVED,
            created_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )


def test_policy_enforces_action_and_required_checked_facts() -> None:
    with pytest.raises(PolicyRejectedError, match="not approved"):
        validate_execution_review(
            plan(), review(), policy(approved_actions=(Action.UPDATE,)), "agent-b", now=NOW
        )


def test_policy_allows_or_rejects_assignee_identifier_types() -> None:
    values = plan().model_dump(exclude={"plan_hash"})
    values["assignees"] = (
        AssigneeRef(identifier_type=AssigneeIdentifierType.OPEN_ID, identifier="ou_example"),
    )
    assigned_plan = PlanV1.build(**values)

    assert (
        validate_execution_review(
            assigned_plan, review(plan=assigned_plan), policy(), "agent-b", now=NOW
        )
        is DeclaredReviewRelationship.INDEPENDENTLY_REVIEWED
    )
    with pytest.raises(PolicyRejectedError, match="assignee identifier type"):
        validate_execution_review(
            assigned_plan,
            review(plan=assigned_plan),
            policy(allowed_assignee_identifier_types=(AssigneeIdentifierType.USER_ID,)),
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


def test_policy_can_reject_warnings_and_old_artifacts() -> None:
    with pytest.raises(PolicyRejectedError, match="warnings"):
        validate_execution_review(
            plan(),
            review(warnings=("Synthetic warning",)),
            policy(reject_warnings=True),
            "agent-b",
            now=NOW,
        )
    with pytest.raises(PolicyRejectedError, match="plan age"):
        validate_execution_review(
            plan(),
            review(),
            policy(max_plan_age_seconds=1),
            "agent-b",
            now=NOW + timedelta(seconds=2),
        )


def test_future_or_predating_review_timestamps_are_blocked() -> None:
    with pytest.raises(PolicyRejectedError, match="future"):
        validate_execution_review(
            plan(),
            review(
                created_at=NOW + timedelta(seconds=1),
                expires_at=NOW + timedelta(minutes=5),
            ),
            policy(),
            "agent-b",
            now=NOW,
        )
    with pytest.raises(PolicyRejectedError, match="predate"):
        validate_execution_review(
            plan(),
            review(
                created_at=NOW - timedelta(seconds=1),
                expires_at=NOW + timedelta(minutes=5),
            ),
            policy(),
            "agent-b",
            now=NOW,
        )


def test_plan_and_review_expire_at_the_exact_boundary() -> None:
    with pytest.raises(PolicyRejectedError, match="review has expired"):
        validate_execution_review(
            plan(),
            review(expires_at=NOW + timedelta(minutes=10)),
            policy(),
            "agent-b",
            now=NOW + timedelta(minutes=10),
        )
    with pytest.raises(PolicyRejectedError, match="plan has expired"):
        validate_execution_review(
            plan(),
            review(expires_at=NOW + timedelta(minutes=30)),
            policy(),
            "agent-b",
            now=NOW + timedelta(minutes=20),
        )
