from __future__ import annotations

import hashlib
import json
from pathlib import Path

from feishu_task_cli.artifacts.canonical import canonical_bytes
from feishu_task_cli.artifacts.plan import PlanV1

VECTORS = Path(__file__).parents[2] / "golden" / "hash-vectors.json"
ARTIFACT_VECTORS = Path(__file__).parents[2] / "golden" / "artifact-vectors.json"


def test_canonical_hash_golden_vectors() -> None:
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))

    for vector in vectors:
        serialized = canonical_bytes(vector["input"])
        assert serialized.decode("utf-8") == vector["canonical"]
        assert hashlib.sha256(serialized).hexdigest() == vector["sha256"]


def test_complete_artifact_golden_vectors() -> None:
    vectors = json.loads(ARTIFACT_VECTORS.read_text(encoding="utf-8"))

    assert any(vector["input"]["action"] != "create" for vector in vectors)

    for vector in vectors:
        assert vector["artifact_type"] == "plan"
        artifact = PlanV1.build(**vector["input"])
        serialized = canonical_bytes(artifact.model_dump(mode="json", exclude={"plan_hash"}))
        assert serialized.decode("utf-8") == vector["canonical"]
        assert artifact.plan_hash == vector["sha256"]
