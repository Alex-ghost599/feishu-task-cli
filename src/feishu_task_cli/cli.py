from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel, ValidationError

from feishu_task_cli.application.reviewer import build_review
from feishu_task_cli.artifacts.plan import PlanV1
from feishu_task_cli.artifacts.policy import PolicyV1
from feishu_task_cli.artifacts.receipt import ReceiptV1
from feishu_task_cli.artifacts.review import CheckedFact, ReviewV1, ReviewVerdict
from feishu_task_cli.errors import ArtifactIntegrityError

app = typer.Typer(help="Agent-native Feishu Task CLI (pre-alpha) with review-gated writes.")
schema_app = typer.Typer(help="Inspect versioned agent artifact schemas.")
app.add_typer(schema_app, name="schema")


def _read_text(source: str) -> str:
    return sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()


def _write_atomic(path: Path, content: bytes) -> None:
    path = path.expanduser()
    if not path.parent.is_dir():
        raise ValueError(f"output directory does not exist: {path.parent}")
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def _is_integrity_validation(error: ValidationError) -> bool:
    return any(
        isinstance(item.get("ctx", {}).get("error"), ArtifactIntegrityError)
        for item in error.errors(include_url=False)
    )


def _fail_json(*, integrity: bool) -> None:
    if integrity:
        code = "artifact_integrity_failed"
        category = "integrity"
        message = "Artifact integrity validation failed."
        exit_code = 8
    else:
        code = "invalid_input"
        category = "input"
        message = "Input could not be safely validated."
        exit_code = 2
    envelope = {
        "error": {
            "category": category,
            "code": code,
            "message": message,
            "retryable": False,
        }
    }
    sys.stdout.buffer.write(_json_bytes(envelope))
    typer.echo(f"error: {code}", err=True)
    raise typer.Exit(exit_code)


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
    output: Annotated[str, typer.Option("--output")] = "-",
) -> None:
    """Create a hash-bound Review artifact for another agent or the same agent."""
    try:
        plan = PlanV1.model_validate_json(_read_text(plan_path))
        review = build_review(
            plan,
            reviewer_id,
            verdict,
            intended_executor_id=intended_executor_id,
            checked_facts=checked_facts or (),
            warnings=warnings or (),
            reasons=reasons or (),
            ttl_seconds=ttl_seconds,
        )
        content = _json_bytes(review.model_dump(mode="json"))
        if output == "-":
            sys.stdout.buffer.write(content)
            typer.echo("created review artifact", err=True)
            return

        destination = Path(output)
        _write_atomic(destination, content)
        envelope = {
            "artifact_hash": review.review_hash,
            "artifact_type": review.artifact_type,
            "path": str(destination),
        }
        sys.stdout.buffer.write(_json_bytes(envelope))
        typer.echo("created review artifact", err=True)
    except ArtifactIntegrityError:
        _fail_json(integrity=True)
    except ValidationError as error:
        _fail_json(integrity=_is_integrity_validation(error))
    except (OSError, UnicodeError, ValueError):
        _fail_json(integrity=False)


@schema_app.command("show")
def schema_show(artifact: Annotated[str, typer.Option("--artifact")]) -> None:
    """Write one artifact JSON Schema to stdout."""
    models: dict[str, type[BaseModel]] = {
        "plan": PlanV1,
        "review": ReviewV1,
        "policy": PolicyV1,
        "receipt": ReceiptV1,
    }
    model = models.get(artifact)
    if model is None:
        raise typer.BadParameter("artifact must be plan, review, policy, or receipt")
    sys.stdout.buffer.write(_json_bytes(model.model_json_schema()))
