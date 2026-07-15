from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from feishu_task_cli.artifacts.base import ArtifactV1, build_hashed_artifact
from feishu_task_cli.artifacts.canonical import artifact_hash
from feishu_task_cli.artifacts.plan import Action, ArtifactHash, AssigneeIdentifierType
from feishu_task_cli.artifacts.review import CheckedFact
from feishu_task_cli.errors import ArtifactIntegrityError


class PolicyContentV1(ArtifactV1):
    artifact_type: Literal["policy"] = "policy"
    require_independent_review: bool = False
    max_plan_age_seconds: int | None = None
    max_review_age_seconds: int | None = None
    approved_actions: tuple[Action, ...] = tuple(Action)
    required_checked_facts: dict[Action, tuple[CheckedFact, ...]] = Field(default_factory=dict)
    reject_warnings: bool = False
    allowed_assignee_identifier_types: tuple[AssigneeIdentifierType, ...] = tuple(
        AssigneeIdentifierType
    )

    @model_validator(mode="after")
    def validate_ages(self) -> PolicyContentV1:
        if self.max_plan_age_seconds is not None and self.max_plan_age_seconds <= 0:
            raise ValueError("max_plan_age_seconds must be positive")
        if self.max_review_age_seconds is not None and self.max_review_age_seconds <= 0:
            raise ValueError("max_review_age_seconds must be positive")
        return self


class PolicyV1(PolicyContentV1):
    policy_hash: ArtifactHash

    @classmethod
    def build(cls, **data: Any) -> Self:
        return build_hashed_artifact(cls, PolicyContentV1.model_validate(data), "policy_hash")

    @model_validator(mode="after")
    def verify_hash(self) -> PolicyV1:
        if self.policy_hash != artifact_hash(self, hash_field="policy_hash"):
            raise ArtifactIntegrityError("policy_hash does not match canonical artifact content")
        return self
