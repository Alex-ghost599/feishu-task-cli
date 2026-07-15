from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from feishu_task_cli import __version__
from feishu_task_cli.artifacts.canonical import artifact_hash
from feishu_task_cli.artifacts.plan import PlanV1
from feishu_task_cli.artifacts.policy import PolicyV1
from feishu_task_cli.artifacts.receipt import DeclaredReviewRelationship
from feishu_task_cli.artifacts.review import ReviewV1, ReviewVerdict
from feishu_task_cli.errors import PolicyRejectedError


def build_neutral_policy(*, created_at: datetime | None = None) -> PolicyV1:
    """Build the public policy with no tenant, target, or identity defaults."""
    return PolicyV1.build(
        created_at=created_at or datetime.now(UTC),
        tool_version=__version__,
    )


def _require_integrity(artifact: Any, hash_field: str, label: str) -> None:
    if getattr(artifact, hash_field) != artifact_hash(artifact, hash_field=hash_field):
        raise PolicyRejectedError(f"{label} hash does not match canonical artifact content")


def validate_execution_review(
    plan: PlanV1,
    review: ReviewV1,
    policy: PolicyV1,
    executor_id: str,
    *,
    now: datetime | None = None,
) -> DeclaredReviewRelationship:
    """Validate declared review evidence and derive its identity relationship."""
    executor = executor_id.strip()
    if not executor:
        raise PolicyRejectedError("executor identity is required")

    _require_integrity(plan, "plan_hash", "plan")
    _require_integrity(review, "review_hash", "review")
    _require_integrity(policy, "policy_hash", "policy")

    timestamp = now or datetime.now(UTC)
    if review.plan_hash != plan.plan_hash:
        raise PolicyRejectedError("review does not bind to the current plan hash")
    if plan.expires_at <= timestamp:
        raise PolicyRejectedError("plan has expired")
    if review.verdict is not ReviewVerdict.APPROVED:
        raise PolicyRejectedError("review verdict must be approved")
    if review.created_at < plan.created_at:
        raise PolicyRejectedError("review predates the plan")
    if review.created_at > timestamp:
        raise PolicyRejectedError("review creation time is in the future")
    if review.expires_at <= timestamp:
        raise PolicyRejectedError("review has expired")
    if review.intended_executor_id is not None and review.intended_executor_id != executor:
        raise PolicyRejectedError("review intended executor does not match executor identity")
    if plan.action not in policy.approved_actions:
        raise PolicyRejectedError(f"action {plan.action.value!r} is not approved by policy")

    required = set(policy.required_checked_facts.get(plan.action, ()))
    missing = required.difference(review.checked_facts)
    if missing:
        values = ", ".join(sorted(item.value for item in missing))
        raise PolicyRejectedError(f"review is missing required checked facts: {values}")

    plan_age = (timestamp - plan.created_at).total_seconds()
    if policy.max_plan_age_seconds is not None and plan_age > policy.max_plan_age_seconds:
        raise PolicyRejectedError("plan age exceeds policy maximum")
    review_age = (timestamp - review.created_at).total_seconds()
    if policy.max_review_age_seconds is not None and review_age > policy.max_review_age_seconds:
        raise PolicyRejectedError("review age exceeds policy maximum")
    if policy.reject_warnings and review.warnings:
        raise PolicyRejectedError("policy rejects reviews containing warnings")

    allowed_assignee_types = set(policy.allowed_assignee_identifier_types)
    if any(assignee.identifier_type not in allowed_assignee_types for assignee in plan.assignees):
        raise PolicyRejectedError("plan contains an assignee identifier type rejected by policy")

    relationship = (
        DeclaredReviewRelationship.SELF_REVIEWED
        if review.reviewer_id == executor
        else DeclaredReviewRelationship.INDEPENDENTLY_REVIEWED
    )
    if policy.require_independent_review and (
        relationship is DeclaredReviewRelationship.SELF_REVIEWED
    ):
        raise PolicyRejectedError(
            "independent review requires different declared identities for reviewer and executor"
        )
    return relationship
