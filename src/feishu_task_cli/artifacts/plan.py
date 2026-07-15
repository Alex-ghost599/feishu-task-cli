from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from feishu_task_cli.artifacts.base import (
    ArtifactV1,
    JsonValueNoFloat,
    NonEmptyString,
    StrictModel,
    UtcDateTime,
    build_hashed_artifact,
)
from feishu_task_cli.artifacts.canonical import artifact_hash, canonical_bytes
from feishu_task_cli.artifacts.task_semantics import (
    normalize_assignee_pairs,
    normalize_task_fields,
)
from feishu_task_cli.errors import ArtifactIntegrityError

Fingerprint = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
DisplayFingerprint = Annotated[str, Field(pattern=r"^[0-9a-f]{12}$")]
ArtifactHash = Fingerprint


class Action(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    ASSIGN = "assign"
    COMPLETE = "complete"


class AssigneeIdentifierType(StrEnum):
    OPEN_ID = "open_id"
    USER_ID = "user_id"
    UNION_ID = "union_id"


class FindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class AuthContext(StrictModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    api_origin: Annotated[
        str,
        Field(pattern=r"^https://[A-Za-z0-9.-]+(?::[0-9]+)?$"),
    ]
    app_id_fingerprint: Fingerprint
    tenant_fingerprint: Fingerprint
    account_fingerprint: Fingerprint
    acting_user_fingerprint: Fingerprint
    app_id_display: DisplayFingerprint
    tenant_display: DisplayFingerprint
    account_display: DisplayFingerprint
    acting_user_display: DisplayFingerprint

    @property
    def actor_fingerprint(self) -> str:
        """Return the acting-user fingerprint under the public actor terminology."""
        return self.acting_user_fingerprint

    @property
    def actor_display(self) -> str:
        """Return the safe acting-user display fingerprint."""
        return self.acting_user_display

    @field_validator("api_origin")
    @classmethod
    def validate_api_origin(cls, value: str) -> str:
        if value != "https://open.feishu.cn":
            raise ValueError("api_origin must be the official Feishu API origin")
        return value

    @model_validator(mode="after")
    def validate_display_fingerprints(self) -> AuthContext:
        pairs = (
            (self.app_id_fingerprint, self.app_id_display),
            (self.tenant_fingerprint, self.tenant_display),
            (self.account_fingerprint, self.account_display),
            (self.acting_user_fingerprint, self.acting_user_display),
        )
        if any(not full.startswith(display) for full, display in pairs):
            raise ValueError("display fingerprint must be a prefix of its full fingerprint")
        return self


class TaskTarget(StrictModel):
    task_guid: NonEmptyString | None = None
    tasklist_guid: NonEmptyString | None = None

    @model_validator(mode="after")
    def require_target(self) -> TaskTarget:
        if self.task_guid is None and self.tasklist_guid is None:
            raise ValueError("at least one task target identifier is required")
        return self


class AssigneeRef(StrictModel):
    identifier_type: AssigneeIdentifierType
    identifier: NonEmptyString
    display_name: NonEmptyString | None = None

    @field_validator("identifier", mode="before")
    @classmethod
    def require_canonical_identifier(cls, value: object) -> object:
        if isinstance(value, str) and (
            value != value.strip() or any(character.isspace() for character in value)
        ):
            raise ValueError("assignee identifier must use canonical non-whitespace form")
        return value


class ValidationFinding(StrictModel):
    code: NonEmptyString
    severity: FindingSeverity
    message: NonEmptyString


class PlanContentV1(ArtifactV1):
    artifact_type: Literal["plan"] = "plan"
    plan_id: NonEmptyString
    action: Action
    target: TaskTarget
    requested_fields: dict[str, JsonValueNoFloat]
    assignees: tuple[AssigneeRef, ...] = ()
    validation_findings: tuple[ValidationFinding, ...] = ()
    required_scopes: tuple[NonEmptyString, ...] = ()
    auth_context: AuthContext
    expires_at: UtcDateTime
    observed_before: dict[str, JsonValueNoFloat] | None = None
    precondition_fingerprint: Fingerprint | None = None

    @field_validator("expires_at")
    @classmethod
    def require_utc_expiry(cls, value: datetime) -> datetime:
        return cls.require_utc(value)

    @model_validator(mode="after")
    def validate_action_requirements(self) -> PlanContentV1:
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        if self.action is Action.CREATE:
            if self.target.task_guid is not None:
                raise ValueError("create plan must not target an existing task_guid")
            if self.observed_before is not None or self.precondition_fingerprint is not None:
                raise ValueError("create plan must not contain an existing-task precondition")
        else:
            if self.target.task_guid is None:
                raise ValueError(f"{self.action.value} plan requires target.task_guid")
            if self.observed_before is None or self.precondition_fingerprint is None:
                raise ValueError(
                    f"{self.action.value} plan requires observed_before and "
                    "precondition_fingerprint"
                )
        if self.action is Action.ASSIGN and not self.assignees:
            raise ValueError("assign plan requires at least one assignee")

        normalized_fields = normalize_task_fields(self.action.value, self.requested_fields)
        if normalized_fields != self.requested_fields:
            raise ValueError("requested_fields must use canonical Task field values")

        pairs = tuple(
            (assignee.identifier_type.value, assignee.identifier) for assignee in self.assignees
        )
        if normalize_assignee_pairs(pairs) != pairs:
            raise ValueError("assignees must be unique and use canonical identifiers")
        if self.action in {Action.UPDATE, Action.COMPLETE} and self.assignees:
            raise ValueError(f"{self.action.value} plan cannot contain assignees")
        if self.action is Action.ASSIGN:
            expected_assignees: list[JsonValueNoFloat] = [
                {"identifier_type": identifier_type, "identifier": identifier}
                for identifier_type, identifier in pairs
            ]
            if self.requested_fields != {"assignees": expected_assignees}:
                raise ValueError("assign requested_fields must match authoritative assignees")

        if self.observed_before is not None:
            observed_fingerprint = hashlib.sha256(canonical_bytes(self.observed_before)).hexdigest()
            if observed_fingerprint != self.precondition_fingerprint:
                raise ValueError("observed_before does not match precondition_fingerprint")
        return self


class PlanV1(PlanContentV1):
    plan_hash: ArtifactHash

    @classmethod
    def build(cls, **data: Any) -> Self:
        return build_hashed_artifact(cls, PlanContentV1.model_validate(data), "plan_hash")

    @model_validator(mode="after")
    def verify_hash(self) -> PlanV1:
        if self.plan_hash != artifact_hash(self, hash_field="plan_hash"):
            raise ArtifactIntegrityError("plan_hash does not match canonical artifact content")
        return self
