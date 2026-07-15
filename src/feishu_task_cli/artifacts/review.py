from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import ValidationInfo, field_validator, model_validator

from feishu_task_cli.artifacts.base import ArtifactV1, NonEmptyString, UtcDateTime, bind_hash
from feishu_task_cli.artifacts.plan import ArtifactHash, Fingerprint


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
    hash_field = "review_hash"
    artifact_type: Literal["review"] = "review"
    plan_hash: Fingerprint
    reviewer_id: NonEmptyString
    intended_executor_id: NonEmptyString | None = None
    verdict: ReviewVerdict
    checked_facts: tuple[CheckedFact, ...] = ()
    warnings: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    expires_at: UtcDateTime
    review_hash: ArtifactHash

    @field_validator("expires_at")
    @classmethod
    def require_utc_expiry(cls, value: datetime) -> datetime:
        return cls.require_utc(value)

    @model_validator(mode="after")
    def validate_and_hash(self, info: ValidationInfo) -> ReviewV1:
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        return bind_hash(self, self.hash_field, info)
