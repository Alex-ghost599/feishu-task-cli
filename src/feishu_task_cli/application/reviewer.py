from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from feishu_task_cli import __version__
from feishu_task_cli.artifacts.plan import PlanV1
from feishu_task_cli.artifacts.review import CheckedFact, ReviewV1, ReviewVerdict


def build_review(
    plan: PlanV1,
    reviewer_id: str,
    verdict: ReviewVerdict,
    *,
    intended_executor_id: str | None = None,
    checked_facts: Iterable[CheckedFact] = (),
    warnings: Iterable[str] = (),
    reasons: Iterable[str] = (),
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
    ttl_seconds: int = 900,
) -> ReviewV1:
    """Build a canonical Review bound to the supplied Plan hash."""
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")
    timestamp = created_at or datetime.now(UTC)
    expiry = expires_at or timestamp + timedelta(seconds=ttl_seconds)
    return ReviewV1.build(
        created_at=timestamp,
        tool_version=__version__,
        plan_hash=plan.plan_hash,
        reviewer_id=reviewer_id,
        intended_executor_id=intended_executor_id,
        verdict=verdict,
        checked_facts=tuple(checked_facts),
        warnings=tuple(warnings),
        reasons=tuple(reasons),
        expires_at=expiry,
    )
