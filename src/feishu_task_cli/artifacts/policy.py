from __future__ import annotations

from typing import Literal

from pydantic import Field, ValidationInfo, model_validator

from feishu_task_cli.artifacts.base import ArtifactV1, bind_hash
from feishu_task_cli.artifacts.plan import Action, ArtifactHash, AssigneeIdentifierType
from feishu_task_cli.artifacts.review import CheckedFact


class PolicyV1(ArtifactV1):
    hash_field = "policy_hash"
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
    policy_hash: ArtifactHash

    @model_validator(mode="after")
    def validate_and_hash(self, info: ValidationInfo) -> PolicyV1:
        if self.max_plan_age_seconds is not None and self.max_plan_age_seconds <= 0:
            raise ValueError("max_plan_age_seconds must be positive")
        if self.max_review_age_seconds is not None and self.max_review_age_seconds <= 0:
            raise ValueError("max_review_age_seconds must be positive")
        return bind_hash(self, self.hash_field, info)
