from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing_extensions import TypeAliasType

from feishu_task_cli.artifacts.canonical import artifact_hash

NonEmptyString = Annotated[str, Field(min_length=1)]
UtcDateTime = Annotated[
    datetime,
    Field(json_schema_extra={"pattern": r"^(?:.*Z|.*[+]00:00)$"}),
]
JsonValueNoFloat = TypeAliasType(
    "JsonValueNoFloat",
    "str | int | bool | None | list[JsonValueNoFloat] | dict[str, JsonValueNoFloat]",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ArtifactV1(StrictModel):
    schema_version: Literal["1"] = "1"
    artifact_type: str
    created_at: UtcDateTime
    tool_version: NonEmptyString

    @field_validator("created_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("timestamp must use UTC")
        return value


ArtifactT = TypeVar("ArtifactT", bound=ArtifactV1)


def build_hashed_artifact(
    artifact_class: type[ArtifactT], content: ArtifactV1, hash_field: str
) -> ArtifactT:
    payload = content.model_dump(mode="python")
    payload[hash_field] = artifact_hash(content, hash_field=hash_field)
    return artifact_class.model_validate(payload)
