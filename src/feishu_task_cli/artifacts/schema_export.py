from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from feishu_task_cli.artifacts.plan import PlanV1
from feishu_task_cli.artifacts.policy import PolicyV1
from feishu_task_cli.artifacts.receipt import ReceiptV1
from feishu_task_cli.artifacts.review import ReviewV1

SCHEMAS: dict[str, type[BaseModel]] = {
    "plan-v1.json": PlanV1,
    "review-v1.json": ReviewV1,
    "policy-v1.json": PolicyV1,
    "receipt-v1.json": ReceiptV1,
}


def export_schemas(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for filename, model in SCHEMAS.items():
        content = json.dumps(
            model.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True
        )
        (path / filename).write_text(content + "\n", encoding="utf-8")


if __name__ == "__main__":
    import sys

    export_schemas(Path(sys.argv[1] if len(sys.argv) > 1 else "schemas"))
