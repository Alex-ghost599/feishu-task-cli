from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import field_validator, model_validator

from feishu_task_cli.artifacts.base import ArtifactV1, bind_hash


class CheckedFact(StrEnum):
    ACTION = "action_checked"
    TARGET_IDENTITY = "target_identity_checked"
    ASSIGNEES = "assignees_checked"
    SCHEDULE = "schedule_checked"
    AUTH_CONTEXT = "auth_context_checked"
    PRECONDITION = "precondition_checked"


class ReviewVerdict(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewV1(ArtifactV1):
    artifact_type: Literal["review"] = "review"
    plan_hash: str
    reviewer_id: str
    intended_executor_id: str | None = None
    verdict: ReviewVerdict
    checked_facts: tuple[CheckedFact, ...] = ()
    warnings: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    expires_at: datetime
    review_hash: str = ""

    @field_validator("expires_at")
    @classmethod
    def require_utc_expiry(cls, value: datetime) -> datetime:
        return cls.require_utc(value)

    @model_validator(mode="after")
    def validate_and_hash(self) -> ReviewV1:
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        return bind_hash(self, "review_hash")
