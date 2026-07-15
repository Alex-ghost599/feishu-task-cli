from __future__ import annotations

import pytest

from feishu_task_cli.artifacts.canonical import artifact_hash, canonical_bytes
from feishu_task_cli.errors import ArtifactIntegrityError


def test_hash_uses_rfc8785_and_excludes_hash_field() -> None:
    value = {"schema_version": "1", "name": "任务", "plan_hash": "ignored"}

    assert artifact_hash(value, hash_field="plan_hash") == artifact_hash(
        {"name": "任务", "schema_version": "1"}, hash_field="plan_hash"
    )


def test_canonical_bytes_are_stable_for_key_order() -> None:
    assert canonical_bytes({"z": 1, "a": "任务"}) == canonical_bytes({"a": "任务", "z": 1})


@pytest.mark.parametrize("value", [1.5, {"nested": [1, 2.5]}, (1.5,)])
def test_float_is_rejected_recursively(value: object) -> None:
    with pytest.raises(ArtifactIntegrityError, match="floating-point"):
        canonical_bytes({"value": value})
