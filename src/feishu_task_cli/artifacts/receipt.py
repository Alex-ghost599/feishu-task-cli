from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from feishu_task_cli.artifacts.base import ArtifactV1, bind_hash
from feishu_task_cli.artifacts.plan import Action, AuthContext


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
    artifact_type: Literal["receipt"] = "receipt"
    action: Action
    plan_hash: str
    review_hash: str
    declared_review_relationship: DeclaredReviewRelationship
    reviewer_id: str
    executor_id: str
    auth_context: AuthContext
    task_guid: str | None = None
    requested_state: dict[str, JsonValue] = Field(default_factory=dict)
    observed_state: dict[str, JsonValue] = Field(default_factory=dict)
    mismatches: tuple[str, ...] = ()
    omitted_fields: tuple[str, ...] = ()
    api_request_id: str | None = None
    started_at: datetime
    completed_at: datetime
    outcome: Outcome
    receipt_hash: str = ""

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        return cls.require_utc(value)

    @model_validator(mode="after")
    def validate_and_hash(self) -> ReceiptV1:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot be earlier than started_at")
        return bind_hash(self, "receipt_hash")
