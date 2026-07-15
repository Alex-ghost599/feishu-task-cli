from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from feishu_task_cli.artifacts.base import (
    ArtifactV1,
    JsonValueNoFloat,
    NonEmptyString,
    UtcDateTime,
    build_hashed_artifact,
)
from feishu_task_cli.artifacts.canonical import artifact_hash
from feishu_task_cli.artifacts.plan import Action, ArtifactHash, AuthContext, Fingerprint
from feishu_task_cli.errors import ArtifactIntegrityError


class Outcome(StrEnum):
    VERIFIED = "verified"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    FAILED = "failed"
    REJECTED = "rejected"


class DeclaredReviewRelationship(StrEnum):
    SELF_REVIEWED = "declared_self_reviewed"
    INDEPENDENTLY_REVIEWED = "declared_independently_reviewed"


class ReceiptContentV1(ArtifactV1):
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
    mismatches: tuple[NonEmptyString, ...] = ()
    omitted_fields: tuple[NonEmptyString, ...] = ()
    api_request_id: NonEmptyString | None = None
    started_at: UtcDateTime
    completed_at: UtcDateTime
    outcome: Outcome

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        return cls.require_utc(value)

    @model_validator(mode="after")
    def validate_receipt(self) -> ReceiptContentV1:
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
        return self


class ReceiptV1(ReceiptContentV1):
    receipt_hash: ArtifactHash

    @classmethod
    def build(cls, **data: Any) -> Self:
        return build_hashed_artifact(cls, ReceiptContentV1.model_validate(data), "receipt_hash")

    @model_validator(mode="after")
    def verify_hash(self) -> ReceiptV1:
        if self.receipt_hash != artifact_hash(self, hash_field="receipt_hash"):
            raise ArtifactIntegrityError("receipt_hash does not match canonical artifact content")
        return self
