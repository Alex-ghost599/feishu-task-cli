from __future__ import annotations

import json
from pathlib import Path

from feishu_task_cli.artifacts.schema_export import SCHEMAS, export_schemas

ROOT = Path(__file__).parents[2]


def test_exported_schemas_match_committed_files(tmp_path: Path) -> None:
    export_schemas(tmp_path)

    for filename in SCHEMAS:
        assert (tmp_path / filename).read_bytes() == (ROOT / "schemas" / filename).read_bytes()


def test_schemas_forbid_unknown_fields() -> None:
    for filename in SCHEMAS:
        schema = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        assert schema["additionalProperties"] is False
        assert schema["properties"]["schema_version"]["const"] == "1"


def test_schemas_require_integrity_hashes() -> None:
    expected = {
        "plan-v1.json": "plan_hash",
        "review-v1.json": "review_hash",
        "policy-v1.json": "policy_hash",
        "receipt-v1.json": "receipt_hash",
    }

    for filename, hash_field in expected.items():
        schema = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        assert hash_field in schema["required"]
