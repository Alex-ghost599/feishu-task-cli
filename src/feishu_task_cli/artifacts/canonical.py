from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import rfc8785
from pydantic import BaseModel

from feishu_task_cli.errors import ArtifactIntegrityError


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=False)
    return value


def _reject_floats(value: Any) -> None:
    if isinstance(value, float):
        raise ArtifactIntegrityError("floating-point values are not allowed in artifacts")
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_floats(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_floats(item)


def canonical_bytes(value: Any) -> bytes:
    normalized = _json_value(value)
    _reject_floats(normalized)
    try:
        return rfc8785.dumps(normalized)
    except (rfc8785.CanonicalizationError, TypeError, ValueError) as exc:
        raise ArtifactIntegrityError(f"artifact cannot be canonicalized: {exc}") from exc


def artifact_hash(value: Any, *, hash_field: str) -> str:
    normalized = _json_value(value)
    if not isinstance(normalized, Mapping):
        raise ArtifactIntegrityError("artifact hash input must be a mapping")
    content = dict(normalized)
    content.pop(hash_field, None)
    return hashlib.sha256(canonical_bytes(content)).hexdigest()
