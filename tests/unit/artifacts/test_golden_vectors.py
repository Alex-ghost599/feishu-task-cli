from __future__ import annotations

import hashlib
import json
from pathlib import Path

from feishu_task_cli.artifacts.canonical import canonical_bytes

VECTORS = Path(__file__).parents[2] / "golden" / "hash-vectors.json"


def test_canonical_hash_golden_vectors() -> None:
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))

    for vector in vectors:
        serialized = canonical_bytes(vector["input"])
        assert serialized.decode("utf-8") == vector["canonical"]
        assert hashlib.sha256(serialized).hexdigest() == vector["sha256"]
