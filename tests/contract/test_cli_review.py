from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from feishu_task_cli.artifacts.plan import Action, AuthContext, PlanV1, TaskTarget
from feishu_task_cli.cli import app

runner = CliRunner()
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def plan_json() -> str:
    artifact = PlanV1.build(
        created_at=NOW,
        tool_version="0.0.0",
        plan_id="plan_example_cli",
        action=Action.CREATE,
        target=TaskTarget(tasklist_guid="tasklist_example"),
        requested_fields={"summary": "Synthetic CLI test"},
        auth_context=AuthContext(
            api_origin="https://open.feishu.cn",
            app_id_fingerprint="1" * 64,
            tenant_fingerprint="2" * 64,
            account_fingerprint="3" * 64,
            acting_user_fingerprint="4" * 64,
            app_id_display="1" * 12,
            tenant_display="2" * 12,
            account_display="3" * 12,
            acting_user_display="4" * 12,
        ),
        expires_at=NOW + timedelta(days=3650),
    )
    return json.dumps(artifact.model_dump(mode="json"))


def review_args() -> list[str]:
    return [
        "review",
        "--plan",
        "-",
        "--reviewer-id",
        "agent-reviewer",
        "--verdict",
        "approved",
    ]


def test_review_reads_stdin_and_emits_one_json_artifact() -> None:
    result = runner.invoke(
        app, [*review_args(), "--checked-fact", "action_checked"], input=plan_json()
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(result.stdout)
    assert artifact["artifact_type"] == "review"
    assert artifact["reviewer_id"] == "agent-reviewer"
    assert artifact["checked_facts"] == ["action_checked"]
    assert "created review" in result.stderr


def test_review_file_output_is_atomic_and_stdout_is_envelope(tmp_path: Path) -> None:
    output = tmp_path / "review.json"
    result = runner.invoke(app, [*review_args(), "--output", str(output)], input=plan_json())

    assert result.exit_code == 0, result.output
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert json.loads(result.stdout) == {
        "artifact_hash": artifact["review_hash"],
        "artifact_type": "review",
        "path": str(output),
    }
    assert not list(tmp_path.glob("*.tmp"))


def test_schema_show_emits_review_contract() -> None:
    result = runner.invoke(app, ["schema", "show", "--artifact", "review"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["properties"]["artifact_type"]["const"] == "review"


def test_cli_does_not_accept_caller_supplied_review_relationship() -> None:
    result = runner.invoke(
        app,
        [*review_args(), "--review-mode", "independent"],
        input=plan_json(),
    )
    assert result.exit_code != 0
    assert "No such option" in result.output
