from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import feishu_task_cli.cli as cli
from feishu_task_cli.application.executor import Executor
from feishu_task_cli.application.planner import Planner
from feishu_task_cli.application.reviewer import build_review
from feishu_task_cli.artifacts.plan import AssigneeIdentifierType, AuthContext
from feishu_task_cli.artifacts.receipt import DeclaredReviewRelationship, Outcome, ReceiptV1
from feishu_task_cli.artifacts.review import ReviewVerdict
from feishu_task_cli.auth.config import Settings
from feishu_task_cli.auth.oauth import AuthStatus
from feishu_task_cli.feishu.tasks import MutationResult, TaskSnapshot
from feishu_task_cli.journal.store import ExecutionJournal

runner = CliRunner()
AUTH = AuthContext(
    api_origin="https://open.feishu.cn",
    app_id_fingerprint="1" * 64,
    tenant_fingerprint="2" * 64,
    account_fingerprint="3" * 64,
    acting_user_fingerprint="4" * 64,
    app_id_display="1" * 12,
    tenant_display="2" * 12,
    account_display="3" * 12,
    acting_user_display="4" * 12,
)


@dataclass
class FakeOAuth:
    logged_out: bool = False

    def status(self) -> AuthStatus:
        return AuthStatus(authenticated=True, auth_context=AUTH)

    def login(self, *, scopes: tuple[str, ...]) -> None:
        assert scopes == ("task:task:read", "task:task:write")

    def logout(self) -> None:
        self.logged_out = True


class FakeGateway:
    def __init__(self) -> None:
        self.tasks: dict[str, TaskSnapshot] = {}
        self.mutations = 0

    def get(
        self,
        task_guid: str,
        *,
        identifier_type: AssigneeIdentifierType = AssigneeIdentifierType.OPEN_ID,
    ) -> TaskSnapshot:
        del identifier_type
        return self.tasks[task_guid]

    def create(
        self, requested_fields: object, assignees: object, *, tasklist_guid: str | None = None
    ) -> MutationResult:
        del assignees, tasklist_guid
        self.mutations += 1
        fields = dict(requested_fields)  # type: ignore[arg-type]
        self.tasks["task_synthetic"] = TaskSnapshot(guid="task_synthetic", fields=fields)
        return MutationResult("task_synthetic", "req-synthetic")

    def update(self, task_guid: str, requested_fields: object) -> MutationResult:
        self.mutations += 1
        fields = dict(self.tasks[task_guid].fields)
        fields.update(dict(requested_fields))  # type: ignore[arg-type]
        self.tasks[task_guid] = TaskSnapshot(guid=task_guid, fields=fields)
        return MutationResult(task_guid, "req-synthetic")

    def assign(self, task_guid: str, assignees: object) -> MutationResult:
        self.mutations += 1
        self.tasks[task_guid] = TaskSnapshot(
            guid=task_guid,
            fields=self.tasks[task_guid].fields,
            assignees=tuple(assignees),  # type: ignore[arg-type]
        )
        return MutationResult(task_guid, "req-synthetic")

    def complete(self, task_guid: str, completed_at: str) -> MutationResult:
        return self.update(task_guid, {"completed_at": completed_at})


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    gateway = FakeGateway()
    oauth = FakeOAuth()
    journal = ExecutionJournal(tmp_path / "journal")
    value = SimpleNamespace(
        oauth=oauth,
        gateway=gateway,
        planner=Planner(gateway, AUTH),
        journal=journal,
        executor=Executor(gateway, auth_context_resolver=lambda: AUTH, journal=journal),
    )
    monkeypatch.setattr(cli, "runtime_factory", lambda **kwargs: value)
    return value


def test_mocked_agent_flow_plan_review_execute_readback_and_render(
    runtime: SimpleNamespace, tmp_path: Path
) -> None:
    plan_path = tmp_path / "plan.json"
    review_path = tmp_path / "review.json"
    receipt_path = tmp_path / "receipt.json"

    planned = runner.invoke(
        cli.app,
        [
            "plan",
            "create",
            "--tasklist-guid",
            "tasklist_synthetic",
            "--input",
            "-",
            "--output",
            str(plan_path),
        ],
        input=json.dumps({"summary": "Synthetic <script> [link](https://attacker.invalid)"}),
    )
    assert planned.exit_code == 0, planned.output
    assert json.loads(planned.stdout)["artifact_type"] == "plan"
    assert "created plan artifact" in planned.stderr

    reviewed = runner.invoke(
        cli.app,
        [
            "review",
            "--plan",
            str(plan_path),
            "--reviewer-id",
            "reviewer-synthetic",
            "--verdict",
            "approved",
            "--output",
            str(review_path),
        ],
    )
    assert reviewed.exit_code == 0, reviewed.output

    executed = runner.invoke(
        cli.app,
        [
            "execute",
            "--plan",
            str(plan_path),
            "--review",
            str(review_path),
            "--executor-id",
            "executor-synthetic",
            "--output",
            str(receipt_path),
        ],
    )
    assert executed.exit_code == 0, executed.output
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["outcome"] == "verified"
    assert runtime.gateway.mutations == 1

    readback = runner.invoke(cli.app, ["task", "get", "--task-guid", "task_synthetic"])
    assert readback.exit_code == 0, readback.output
    assert json.loads(readback.stdout)["task"]["guid"] == "task_synthetic"

    rendered = runner.invoke(
        cli.app,
        ["render", "--artifact", str(receipt_path), "--format", "markdown"],
    )
    assert rendered.exit_code == 0, rendered.output
    assert "Execution outcome: `verified`" in rendered.stdout
    assert "https://attacker.invalid" not in rendered.stdout
    assert rendered.stderr == ""


def test_file_output_is_private_and_rejects_symlink(
    runtime: SimpleNamespace, tmp_path: Path
) -> None:
    output = tmp_path / "plan.json"
    result = runner.invoke(
        cli.app,
        [
            "plan",
            "create",
            "--tasklist-guid",
            "tasklist_synthetic",
            "--input",
            "-",
            "--output",
            str(output),
        ],
        input='{"summary":"Synthetic"}',
    )
    assert result.exit_code == 0
    assert stat.S_IMODE(output.stat().st_mode) == 0o600

    target = tmp_path / "target.json"
    target.write_text("preserve", encoding="utf-8")
    link = tmp_path / "linked.json"
    link.symlink_to(target)
    rejected = runner.invoke(
        cli.app,
        [
            "plan",
            "create",
            "--tasklist-guid",
            "tasklist_synthetic",
            "--input",
            "-",
            "--output",
            str(link),
        ],
        input='{"summary":"Synthetic"}',
    )
    assert rejected.exit_code == 2
    assert target.read_text(encoding="utf-8") == "preserve"

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    (real_parent / "sub").mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    ancestor_rejected = runner.invoke(
        cli.app,
        [
            "plan",
            "create",
            "--tasklist-guid",
            "tasklist_synthetic",
            "--input",
            "-",
            "--output",
            str(linked_parent / "sub" / "artifact.json"),
        ],
        input='{"summary":"Synthetic"}',
    )
    assert ancestor_rejected.exit_code == 2
    assert not (real_parent / "sub" / "artifact.json").exists()

    shared_parent = tmp_path / "shared-parent"
    shared_parent.mkdir(mode=0o777)
    shared_parent.chmod(0o777)
    shared_rejected = runner.invoke(
        cli.app,
        [
            "plan",
            "create",
            "--tasklist-guid",
            "tasklist_synthetic",
            "--summary",
            "Synthetic",
            "--output",
            str(shared_parent / "artifact.json"),
        ],
    )
    assert shared_rejected.exit_code == 2
    assert not (shared_parent / "artifact.json").exists()


def test_auth_and_execution_status_commands_are_json_and_non_prompting(
    runtime: SimpleNamespace, tmp_path: Path
) -> None:
    status = runner.invoke(cli.app, ["auth", "status"])
    assert status.exit_code == 0
    assert json.loads(status.stdout)["authenticated"] is True
    assert "app_id_fingerprint" in json.loads(status.stdout)["auth_context"]

    logout = runner.invoke(cli.app, ["auth", "logout"])
    assert logout.exit_code == 0
    assert json.loads(logout.stdout) == {"authenticated": False}
    assert runtime.oauth.logged_out

    missing = runner.invoke(
        cli.app,
        [
            "execution",
            "status",
            "--plan-hash",
            "a" * 64,
            "--journal-dir",
            str(tmp_path / "status-journal"),
        ],
    )
    assert missing.exit_code == 0
    assert json.loads(missing.stdout) == {"plan_hash": "a" * 64, "state": "not_started"}


def test_execution_status_does_not_require_authentication_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def forbidden_runtime(**kwargs: object) -> object:
        pytest.fail(f"authentication runtime must not be built: {kwargs}")

    monkeypatch.setattr(cli, "runtime_factory", forbidden_runtime)
    result = runner.invoke(
        cli.app,
        [
            "execution",
            "status",
            "--plan-hash",
            "b" * 64,
            "--journal-dir",
            str(tmp_path / "journal"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "plan_hash": "b" * 64,
        "state": "not_started",
    }


def test_runtime_refreshes_stored_credentials_when_access_token_is_absent() -> None:
    class RefreshingOAuth:
        def __init__(self) -> None:
            self.token: str | None = None
            self.refreshed = 0

        def access_token(self) -> str | None:
            return self.token

        def refresh(self) -> None:
            self.refreshed += 1
            self.token = "synthetic-refreshed-token"

    oauth = RefreshingOAuth()
    runtime = cli.Runtime(
        settings=Settings(app_id="app_synthetic", account_id="account_synthetic"),
        oauth=oauth,  # type: ignore[arg-type]
    )

    assert runtime._access_token() == "synthetic-refreshed-token"
    assert oauth.refreshed == 1


def test_remaining_plan_and_explicit_human_auth_login_are_machine_readable(
    runtime: SimpleNamespace,
) -> None:
    runtime.gateway.tasks["task_existing"] = TaskSnapshot(
        guid="task_existing",
        fields={"summary": "Before", "completed_at": "0"},
    )

    login = runner.invoke(cli.app, ["auth", "login"])
    assert login.exit_code == 0, login.output
    assert json.loads(login.stdout)["authenticated"] is True

    update = runner.invoke(
        cli.app,
        ["plan", "update", "--task-guid", "task_existing", "--summary", "After"],
    )
    assert update.exit_code == 0, update.output
    assert json.loads(update.stdout)["action"] == "update"

    assign = runner.invoke(
        cli.app,
        [
            "plan",
            "assign",
            "--task-guid",
            "task_existing",
            "--assignee",
            "open_id:ou_synthetic",
        ],
    )
    assert assign.exit_code == 0, assign.output
    assert json.loads(assign.stdout)["action"] == "assign"

    complete = runner.invoke(
        cli.app,
        ["plan", "complete", "--task-guid", "task_existing"],
    )
    assert complete.exit_code == 0, complete.output
    assert json.loads(complete.stdout)["action"] == "complete"


def test_render_and_schema_file_outputs_keep_json_envelopes(
    runtime: SimpleNamespace, tmp_path: Path
) -> None:
    plan_path = tmp_path / "plan.json"
    markdown_path = tmp_path / "plan.md"
    schema_path = tmp_path / "schema.json"
    planned = runner.invoke(
        cli.app,
        [
            "plan",
            "create",
            "--tasklist-guid",
            "tasklist_synthetic",
            "--summary",
            "Synthetic",
            "--output",
            str(plan_path),
        ],
    )
    assert planned.exit_code == 0, planned.output

    rendered = runner.invoke(
        cli.app,
        [
            "render",
            "--artifact",
            str(plan_path),
            "--format",
            "markdown",
            "--output",
            str(markdown_path),
        ],
    )
    assert rendered.exit_code == 0, rendered.output
    assert json.loads(rendered.stdout) == {
        "artifact_type": "markdown",
        "format": "markdown",
        "path": str(markdown_path),
    }
    assert stat.S_IMODE(markdown_path.stat().st_mode) == 0o600

    schema = runner.invoke(
        cli.app,
        ["schema", "show", "--artifact", "receipt", "--output", str(schema_path)],
    )
    assert schema.exit_code == 0, schema.output
    assert json.loads(schema.stdout) == {
        "artifact_type": "json_schema",
        "path": str(schema_path),
    }
    assert json.loads(schema_path.read_text(encoding="utf-8"))["title"] == "ReceiptV1"


@pytest.mark.parametrize(
    ("outcome", "expected_exit"),
    [(Outcome.PARTIAL, 7), (Outcome.UNKNOWN, 6), (Outcome.FAILED, 5)],
)
def test_execute_non_verified_receipt_keeps_artifact_envelope_and_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    outcome: Outcome,
    expected_exit: int,
) -> None:
    now = datetime.now(UTC)
    plan = Planner(FakeGateway(), AUTH).create(
        requested_fields={"summary": "Synthetic"},
        tasklist_guid="tasklist_synthetic",
    )
    review = build_review(
        plan,
        "reviewer-synthetic",
        ReviewVerdict.APPROVED,
    )
    plan_path = tmp_path / f"plan-{outcome.value}.json"
    review_path = tmp_path / f"review-{outcome.value}.json"
    receipt_path = tmp_path / f"receipt-{outcome.value}.json"
    plan_path.write_text(plan.model_dump_json(), encoding="utf-8")
    review_path.write_text(review.model_dump_json(), encoding="utf-8")

    class OutcomeExecutor:
        def execute(self, *args: object, **kwargs: object) -> ReceiptV1:
            del args, kwargs
            is_partial = outcome is Outcome.PARTIAL
            return ReceiptV1.build(
                created_at=now,
                tool_version="0.0.0",
                action=plan.action,
                plan_hash=plan.plan_hash,
                review_hash=review.review_hash,
                declared_review_relationship=(DeclaredReviewRelationship.INDEPENDENTLY_REVIEWED),
                reviewer_id="reviewer-synthetic",
                executor_id="executor-synthetic",
                auth_context=AUTH,
                task_guid="task_synthetic" if is_partial else None,
                requested_state={"summary": "Synthetic"},
                observed_state={"summary": "Different"} if is_partial else {},
                mismatches=("summary",) if is_partial else (),
                started_at=now,
                completed_at=now,
                outcome=outcome,
            )

    monkeypatch.setattr(
        cli,
        "runtime_factory",
        lambda **kwargs: SimpleNamespace(executor=OutcomeExecutor()),
    )
    result = runner.invoke(
        cli.app,
        [
            "execute",
            "--plan",
            str(plan_path),
            "--review",
            str(review_path),
            "--executor-id",
            "executor-synthetic",
            "--output",
            str(receipt_path),
        ],
    )

    assert result.exit_code == expected_exit, result.output
    assert json.loads(result.stdout)["artifact_type"] == "receipt"
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["outcome"] == outcome.value
    assert result.stderr.strip() == "created execution receipt"


def test_production_runtime_assembly_is_lazy_and_uses_explicit_identity() -> None:
    class AssemblyOAuth:
        api_origin = "https://open.feishu.cn"
        app_id = "app_synthetic"

        def access_token(self) -> str:
            return "synthetic-access-token"

        def get_identity(self) -> dict[str, str]:
            return {
                "tenant_id": "tenant_synthetic",
                "union_id": "union_synthetic",
                "open_id": "ou_synthetic",
            }

    runtime = cli.Runtime(
        settings=Settings(app_id="app_synthetic", account_id="union_synthetic"),
        oauth=AssemblyOAuth(),  # type: ignore[arg-type]
    )

    assert runtime.gateway is runtime.gateway
    assert runtime.planner is runtime.planner
    assert runtime.executor is runtime.executor


def test_execute_malformed_yaml_policy_is_invalid_input(
    runtime: SimpleNamespace, tmp_path: Path
) -> None:
    plan = runtime.planner.create(
        requested_fields={"summary": "Synthetic"},
        tasklist_guid="tasklist_synthetic",
    )
    review = build_review(plan, "reviewer-synthetic", ReviewVerdict.APPROVED)
    plan_path = tmp_path / "plan.json"
    review_path = tmp_path / "review.json"
    policy_path = tmp_path / "policy.yaml"
    plan_path.write_text(plan.model_dump_json(), encoding="utf-8")
    review_path.write_text(review.model_dump_json(), encoding="utf-8")
    policy_path.write_text("rules: [unterminated", encoding="utf-8")

    result = runner.invoke(
        cli.app,
        [
            "execute",
            "--plan",
            str(plan_path),
            "--review",
            str(review_path),
            "--policy",
            str(policy_path),
            "--executor-id",
            "executor-synthetic",
        ],
    )

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "invalid_input"
    assert json.loads(result.stdout)["error"]["next_action"] == "fix_invalid_input"
    assert runtime.gateway.mutations == 0
