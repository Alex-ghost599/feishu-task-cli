from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from feishu_task_cli.artifacts.plan import Action, AuthContext, PlanV1, TaskTarget
from feishu_task_cli.cli import app

runner = CliRunner()
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def plan_json() -> str:
    plan = PlanV1.build(
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
    return json.dumps(plan.model_dump(mode="json"))


def test_review_reads_plan_from_stdin_and_emits_one_json_artifact() -> None:
    result = runner.invoke(
        app,
        [
            "review",
            "--plan",
            "-",
            "--reviewer-id",
            "agent-reviewer",
            "--verdict",
            "approved",
            "--checked-fact",
            "action_checked",
            "--output",
            "-",
        ],
        input=plan_json(),
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(result.stdout)
    assert artifact["artifact_type"] == "review"
    assert artifact["reviewer_id"] == "agent-reviewer"
    assert artifact["checked_facts"] == ["action_checked"]
    assert "created review" in result.stderr


def test_review_file_output_is_atomic_and_stdout_is_result_envelope(tmp_path: Path) -> None:
    output = tmp_path / "review.json"
    result = runner.invoke(
        app,
        [
            "review",
            "--plan",
            "-",
            "--reviewer-id",
            "agent-reviewer",
            "--verdict",
            "approved",
            "--output",
            str(output),
        ],
        input=plan_json(),
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert envelope == {
        "artifact_hash": artifact["review_hash"],
        "artifact_type": "review",
        "path": str(output),
    }
    assert not list(tmp_path.glob("*.tmp"))


def test_schema_show_emits_committed_contract() -> None:
    result = runner.invoke(app, ["schema", "show", "--artifact", "review"])

    assert result.exit_code == 0
    schema = json.loads(result.stdout)
    committed = Path("schemas/review-v1.json").read_text(encoding="utf-8")
    assert schema == json.loads(committed)


def test_cli_does_not_accept_caller_supplied_review_relationship() -> None:
    result = runner.invoke(
        app,
        [
            "review",
            "--plan",
            "-",
            "--reviewer-id",
            "agent-reviewer",
            "--verdict",
            "approved",
            "--review-mode",
            "independent",
        ],
        input=plan_json(),
    )

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "invalid_input"
    assert result.stderr.strip() == "error: invalid_input"


def _run_real_cli(plan_input: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "feishu_task_cli",
            "review",
            "--plan",
            "-",
            "--reviewer-id",
            "agent-reviewer",
            "--verdict",
            "approved",
        ],
        input=plan_input,
        text=True,
        capture_output=True,
        check=False,
    )


def test_real_cli_invalid_json_is_redacted_agent_error() -> None:
    result = _run_real_cli("{not-json")

    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "error": {
            "category": "input",
            "code": "invalid_input",
            "message": "Input could not be safely validated.",
            "next_action": "fix_invalid_input",
            "next_action_mapping_version": "v1",
            "retryable": False,
        }
    }
    assert result.stderr.strip() == "error: invalid_input"
    assert "Traceback" not in result.stderr
    assert "/Users/" not in result.stderr


def test_real_cli_parser_error_is_stable_json() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "feishu_task_cli", "plan", "create"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["error"] == {
        "category": "input",
        "code": "invalid_input",
        "message": "Input could not be safely validated.",
        "next_action": "fix_invalid_input",
        "next_action_mapping_version": "v1",
        "retryable": False,
    }
    assert result.stderr.strip() == "error: invalid_input"


def test_real_cli_tampered_plan_uses_integrity_exit_code() -> None:
    payload = json.loads(plan_json())
    payload["requested_fields"] = {"summary": "Tampered"}
    result = _run_real_cli(json.dumps(payload))

    assert result.returncode == 8
    assert json.loads(result.stdout)["error"]["code"] == "artifact_integrity_failed"
    assert result.stderr.strip() == "error: artifact_integrity_failed"
    assert "/Users/" not in result.stderr
