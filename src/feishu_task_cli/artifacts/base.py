from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, field_validator

from feishu_task_cli.artifacts.canonical import artifact_hash


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactV1(StrictModel):
    schema_version: Literal["1"] = "1"
    artifact_type: str
    created_at: datetime
    tool_version: str

    @field_validator("created_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("timestamp must use UTC")
        return value


ArtifactT = TypeVar("ArtifactT", bound=ArtifactV1)


def bind_hash(artifact: ArtifactT, hash_field: str) -> ArtifactT:
    expected = artifact_hash(artifact, hash_field=hash_field)
    supplied = getattr(artifact, hash_field)
    if supplied and supplied != expected:
        raise ValueError(f"{hash_field} does not match canonical artifact content")
    object.__setattr__(artifact, hash_field, expected)
    return artifact
