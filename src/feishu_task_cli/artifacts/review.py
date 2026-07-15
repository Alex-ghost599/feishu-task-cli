from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import field_validator, model_validator

from feishu_task_cli.artifacts.base import (
    ArtifactV1,
    NonEmptyString,
    UtcDateTime,
    build_hashed_artifact,
)
from feishu_task_cli.artifacts.canonical import artifact_hash
from feishu_task_cli.artifacts.plan import ArtifactHash, Fingerprint
from feishu_task_cli.errors import ArtifactIntegrityError


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


class ReviewContentV1(ArtifactV1):
    artifact_type: Literal["review"] = "review"
    plan_hash: Fingerprint
    reviewer_id: NonEmptyString
    intended_executor_id: NonEmptyString | None = None
    verdict: ReviewVerdict
    checked_facts: tuple[CheckedFact, ...] = ()
    warnings: tuple[NonEmptyString, ...] = ()
    reasons: tuple[NonEmptyString, ...] = ()
    expires_at: UtcDateTime

    @field_validator("expires_at")
    @classmethod
    def require_utc_expiry(cls, value: datetime) -> datetime:
        return cls.require_utc(value)

    @model_validator(mode="after")
    def validate_expiry(self) -> ReviewContentV1:
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        return self


class ReviewV1(ReviewContentV1):
    review_hash: ArtifactHash

    @classmethod
    def build(cls, **data: Any) -> Self:
        return build_hashed_artifact(cls, ReviewContentV1.model_validate(data), "review_hash")

    @model_validator(mode="after")
    def verify_hash(self) -> ReviewV1:
        if self.review_hash != artifact_hash(self, hash_field="review_hash"):
            raise ArtifactIntegrityError("review_hash does not match canonical artifact content")
        return self
