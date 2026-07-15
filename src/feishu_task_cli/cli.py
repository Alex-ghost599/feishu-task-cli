from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import BaseModel

from feishu_task_cli.application.reviewer import build_review
from feishu_task_cli.artifacts.plan import PlanV1
from feishu_task_cli.artifacts.policy import PolicyV1
from feishu_task_cli.artifacts.receipt import ReceiptV1
from feishu_task_cli.artifacts.review import CheckedFact, ReviewV1, ReviewVerdict

app = typer.Typer(help="Agent-native Feishu Task CLI (pre-alpha) with review-gated execution.")
schema_app = typer.Typer(help="Inspect stable JSON artifact contracts.")
app.add_typer(schema_app, name="schema")

ArtifactName = Annotated[
    str,
    typer.Option("--artifact", help="Artifact contract: plan, review, policy, or receipt."),
]


def _read_text(path: str) -> str:
    if path == "-":
        return typer.get_text_stream("stdin").read()
    return Path(path).read_text(encoding="utf-8")


def _json_line(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


@app.command("review")
def review_command(
    plan_path: Annotated[str, typer.Option("--plan", help="Plan JSON path, or - for stdin.")],
    reviewer_id: Annotated[str, typer.Option("--reviewer-id")],
    verdict: Annotated[ReviewVerdict, typer.Option("--verdict")],
    intended_executor_id: Annotated[str | None, typer.Option("--intended-executor-id")] = None,
    checked_facts: Annotated[list[CheckedFact] | None, typer.Option("--checked-fact")] = None,
    warnings: Annotated[list[str] | None, typer.Option("--warning")] = None,
    reasons: Annotated[list[str] | None, typer.Option("--reason")] = None,
    ttl_seconds: Annotated[int, typer.Option("--ttl-seconds", min=1)] = 900,
    output: Annotated[
        str, typer.Option("--output", help="Output JSON path, or - for stdout.")
    ] = "-",
) -> None:
    """Create canonical declared review evidence for a Plan."""
    plan = PlanV1.model_validate_json(_read_text(plan_path))
    artifact = build_review(
        plan,
        reviewer_id,
        verdict,
        intended_executor_id=intended_executor_id,
        checked_facts=checked_facts or (),
        warnings=warnings or (),
        reasons=reasons or (),
        ttl_seconds=ttl_seconds,
    )
    content = _json_line(artifact.model_dump(mode="json")) + "\n"
    if output == "-":
        typer.echo(content, nl=False)
    else:
        output_path = Path(output)
        _write_atomic(output_path, content)
        typer.echo(
            _json_line(
                {
                    "artifact_hash": artifact.review_hash,
                    "artifact_type": artifact.artifact_type,
                    "path": str(output_path),
                }
            )
        )
    typer.echo(f"created review {artifact.review_hash}", err=True)


@schema_app.command("show")
def schema_show(artifact: ArtifactName) -> None:
    """Emit one artifact JSON Schema to stdout."""
    models: dict[str, type[BaseModel]] = {
        "plan": PlanV1,
        "review": ReviewV1,
        "policy": PolicyV1,
        "receipt": ReceiptV1,
    }
    model = models.get(artifact)
    if model is None:
        raise typer.BadParameter(
            "must be one of: plan, review, policy, receipt", param_hint="--artifact"
        )
    typer.echo(_json_line(model.model_json_schema()))
