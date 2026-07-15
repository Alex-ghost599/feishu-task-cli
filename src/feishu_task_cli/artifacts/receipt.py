from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator

from feishu_task_cli.artifacts.base import (
    ArtifactV1,
    JsonValueNoFloat,
    NonEmptyString,
    UtcDateTime,
    bind_hash,
)
from feishu_task_cli.artifacts.plan import Action, ArtifactHash, AuthContext, Fingerprint


class Outcome(StrEnum):
    VERIFIED = "verified"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    FAILED = "failed"
    REJECTED = "rejected"


class DeclaredReviewRelationship(StrEnum):
    SELF_REVIEWED = "declared_self_reviewed"
    INDEPENDENTLY_REVIEWED = "declared_independently_reviewed"


class ReceiptV1(ArtifactV1):
    hash_field = "receipt_hash"
    artifact_type: Literal["receipt"] = "receipt"
    action: Action
    plan_hash: Fingerprint
    review_hash: Fingerprint
    declared_review_relationship: DeclaredReviewRelationship
    reviewer_id: NonEmptyString
    executor_id: NonEmptyString
    auth_context: AuthContext
    task_guid: NonEmptyString | None = None
    requested_state: dict[str, JsonValueNoFloat] = Field(default_factory=dict)
    observed_state: dict[str, JsonValueNoFloat] = Field(default_factory=dict)
    mismatches: tuple[str, ...] = ()
    omitted_fields: tuple[str, ...] = ()
    api_request_id: NonEmptyString | None = None
    started_at: UtcDateTime
    completed_at: UtcDateTime
    outcome: Outcome
    receipt_hash: ArtifactHash

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        return cls.require_utc(value)

    @model_validator(mode="after")
    def validate_and_hash(self, info: ValidationInfo) -> ReceiptV1:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot be earlier than started_at")
        is_self = self.reviewer_id == self.executor_id
        if is_self != (
            self.declared_review_relationship is DeclaredReviewRelationship.SELF_REVIEWED
        ):
            raise ValueError("declared review relationship does not match agent identities")
        if self.outcome in (Outcome.VERIFIED, Outcome.PARTIAL) and self.task_guid is None:
            raise ValueError(f"{self.outcome.value} receipt requires task_guid")
        if self.outcome is Outcome.VERIFIED:
            if self.mismatches or self.omitted_fields:
                raise ValueError("verified receipt cannot contain mismatches or omitted fields")
            if any(
                self.observed_state.get(key) != value for key, value in self.requested_state.items()
            ):
                raise ValueError("verified receipt requested state must match observed state")
        if self.outcome is Outcome.PARTIAL and not (self.mismatches or self.omitted_fields):
            raise ValueError("partial receipt requires a mismatch or omitted field")
        return bind_hash(self, self.hash_field, info)
