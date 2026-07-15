from __future__ import annotations

from datetime import UTC, datetime

from feishu_task_cli import __version__
from feishu_task_cli.artifacts.canonical import artifact_hash
from feishu_task_cli.artifacts.plan import Action, PlanV1
from feishu_task_cli.artifacts.policy import PolicyV1
from feishu_task_cli.artifacts.receipt import DeclaredReviewRelationship
from feishu_task_cli.artifacts.review import CheckedFact, ReviewV1, ReviewVerdict
from feishu_task_cli.errors import PolicyRejectedError

STRICT_REQUIRED_FACTS = {
    Action.CREATE: (
        CheckedFact.ACTION,
        CheckedFact.TARGET_IDENTITY,
        CheckedFact.ASSIGNEES,
        CheckedFact.SCHEDULE,
        CheckedFact.AUTH_CONTEXT,
    ),
    Action.UPDATE: (
        CheckedFact.ACTION,
        CheckedFact.TARGET_IDENTITY,
        CheckedFact.SCHEDULE,
        CheckedFact.AUTH_CONTEXT,
        CheckedFact.PRECONDITION,
    ),
    Action.ASSIGN: (
        CheckedFact.ACTION,
        CheckedFact.TARGET_IDENTITY,
        CheckedFact.ASSIGNEES,
        CheckedFact.AUTH_CONTEXT,
        CheckedFact.PRECONDITION,
    ),
    Action.COMPLETE: (
        CheckedFact.ACTION,
        CheckedFact.TARGET_IDENTITY,
        CheckedFact.AUTH_CONTEXT,
        CheckedFact.PRECONDITION,
    ),
}


def build_neutral_policy(*, created_at: datetime | None = None) -> PolicyV1:
    """Build the default policy: approved and unexpired review, either relationship."""
    return PolicyV1.build(
        created_at=created_at or datetime.now(UTC),
        tool_version=__version__,
    )


def build_strict_policy(*, created_at: datetime | None = None) -> PolicyV1:
    """Build the bundled independent-review policy with action-specific checks."""
    return PolicyV1.build(
        created_at=created_at or datetime.now(UTC),
        tool_version=__version__,
        require_independent_review=True,
        required_checked_facts=STRICT_REQUIRED_FACTS,
        reject_warnings=True,
    )


def _require_integrity(artifact: object, hash_field: str, label: str) -> None:
    supplied = getattr(artifact, hash_field)
    if artifact_hash(artifact, hash_field=hash_field) != supplied:
        raise PolicyRejectedError(f"{label} hash integrity check failed")


def validate_execution_review(
    plan: PlanV1,
    review: ReviewV1,
    policy: PolicyV1,
    executor_id: str,
    *,
    now: datetime | None = None,
) -> DeclaredReviewRelationship:
    """Validate review/policy inputs and derive, never accept, the review relationship."""
    current = now or datetime.now(UTC)
    declared_executor = executor_id.strip()
    if not declared_executor:
        raise PolicyRejectedError("executor identity is required")

    _require_integrity(plan, "plan_hash", "plan")
    _require_integrity(review, "review_hash", "review")
    _require_integrity(policy, "policy_hash", "policy")

    if review.plan_hash != plan.plan_hash:
        raise PolicyRejectedError("review plan hash does not match the execution plan hash")
    if review.verdict is not ReviewVerdict.APPROVED:
        raise PolicyRejectedError("review verdict must be approved")
    if plan.created_at > current or review.created_at > current:
        raise PolicyRejectedError("plan and review creation times cannot be in the future")
    if review.created_at < plan.created_at:
        raise PolicyRejectedError("review cannot predate the plan it approves")
    if current >= plan.expires_at:
        raise PolicyRejectedError("plan has expired")
    if current >= review.expires_at:
        raise PolicyRejectedError("review has expired")
    if review.intended_executor_id and review.intended_executor_id != declared_executor:
        raise PolicyRejectedError("review intended executor does not match executor identity")
    if plan.action not in policy.approved_actions:
        raise PolicyRejectedError(f"action {plan.action.value} is not approved by policy")

    plan_age = (current - plan.created_at).total_seconds()
    review_age = (current - review.created_at).total_seconds()
    if policy.max_plan_age_seconds is not None and plan_age > policy.max_plan_age_seconds:
        raise PolicyRejectedError("plan age exceeds policy limit")
    if policy.max_review_age_seconds is not None and review_age > policy.max_review_age_seconds:
        raise PolicyRejectedError("review age exceeds policy limit")
    if policy.reject_warnings and review.warnings:
        raise PolicyRejectedError("policy rejects reviews containing warnings")

    required = set(policy.required_checked_facts.get(plan.action, ()))
    missing = required.difference(review.checked_facts)
    if missing:
        values = ", ".join(sorted(item.value for item in missing))
        raise PolicyRejectedError(f"review is missing required checked facts: {values}")

    disallowed_assignees = [
        assignee.identifier_type
        for assignee in plan.assignees
        if assignee.identifier_type not in policy.allowed_assignee_identifier_types
    ]
    if disallowed_assignees:
        raise PolicyRejectedError("plan contains an assignee identifier type rejected by policy")

    relationship = (
        DeclaredReviewRelationship.SELF_REVIEWED
        if review.reviewer_id == declared_executor
        else DeclaredReviewRelationship.INDEPENDENTLY_REVIEWED
    )
    if policy.require_independent_review and (
        relationship is DeclaredReviewRelationship.SELF_REVIEWED
    ):
        raise PolicyRejectedError("policy requires different declared identities")
    return relationship
