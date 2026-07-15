from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from feishu_task_cli import __version__
from feishu_task_cli.application.executor import (
    Executor,
    exit_code_for_error,
    exit_code_for_receipt,
)
from feishu_task_cli.application.policy_engine import build_neutral_policy
from feishu_task_cli.application.reviewer import build_review
from feishu_task_cli.artifacts.plan import (
    Action,
    AssigneeIdentifierType,
    AssigneeRef,
    AuthContext,
    FindingSeverity,
    PlanV1,
    TaskTarget,
    ValidationFinding,
)
from feishu_task_cli.artifacts.receipt import Outcome
from feishu_task_cli.artifacts.review import ReviewVerdict
from feishu_task_cli.auth.context import build_auth_context
from feishu_task_cli.errors import (
    ArtifactIntegrityError,
    AuthContextMismatchError,
    FeishuResponseError,
    PolicyRejectedError,
    PreconditionChangedError,
    ReplayBlockedError,
)
from feishu_task_cli.feishu.client import FeishuAPIError, FeishuTransportError
from feishu_task_cli.feishu.tasks import MutationResult, TaskSnapshot
from feishu_task_cli.journal.store import ExecutionJournal, ExecutionState

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
AUTH = build_auth_context(
    api_origin="https://open.feishu.cn",
    app_id="cli_synthetic",
    tenant_id="tenant_synthetic",
    account_id="account_synthetic",
    actor_id="actor_synthetic",
)


class StubGateway:
    def __init__(self, observed: list[TaskSnapshot]) -> None:
        self.observed = list(observed)
        self.mutations = 0
        self.failure: BaseException | None = None
        self.get_failure: BaseException | None = None

    def get(self, task_guid: str, **kwargs: object) -> TaskSnapshot:
        assert task_guid == "task_synthetic"
        if self.get_failure is not None:
            raise self.get_failure
        return self.observed.pop(0)

    def _mutate(self) -> MutationResult:
        self.mutations += 1
        if self.failure is not None:
            raise self.failure
        return MutationResult(task_guid="task_synthetic", request_id="req-synthetic")

    def create(self, *args: object, **kwargs: object) -> MutationResult:
        return self._mutate()

    def update(self, *args: object, **kwargs: object) -> MutationResult:
        return self._mutate()

    def assign(self, *args: object, **kwargs: object) -> MutationResult:
        return self._mutate()

    def complete(self, *args: object, **kwargs: object) -> MutationResult:
        return self._mutate()


def create_plan() -> PlanV1:
    return PlanV1.build(
        created_at=NOW,
        tool_version=__version__,
        plan_id="plan_synthetic",
        action=Action.CREATE,
        target=TaskTarget(tasklist_guid="tasklist_synthetic"),
        requested_fields={"summary": "Expected"},
        auth_context=AUTH,
        expires_at=NOW + timedelta(minutes=15),
    )


def existing_plan(before: TaskSnapshot) -> PlanV1:
    return PlanV1.build(
        created_at=NOW,
        tool_version=__version__,
        plan_id="plan_existing_synthetic",
        action=Action.UPDATE,
        target=TaskTarget(task_guid="task_synthetic"),
        requested_fields={"summary": "Expected"},
        auth_context=AUTH,
        expires_at=NOW + timedelta(minutes=15),
        observed_before=before.to_state(),
        precondition_fingerprint=before.fingerprint(),
    )


def approved(plan: PlanV1):
    return build_review(
        plan,
        "agent-reviewer",
        ReviewVerdict.APPROVED,
        intended_executor_id="agent-executor",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )


def executor(gateway: StubGateway, root: Path, auth: AuthContext = AUTH) -> Executor:
    return Executor(
        gateway,
        auth_context_resolver=lambda: auth,
        journal=ExecutionJournal(root),
        now=lambda: NOW + timedelta(seconds=2),
    )


def test_verified_execution_mutates_once_reads_returned_guid_and_records_receipt(
    tmp_path: Path,
) -> None:
    plan = create_plan()
    gateway = StubGateway([TaskSnapshot(guid="task_synthetic", fields={"summary": "Expected"})])
    receipt = executor(gateway, tmp_path / "journal").execute(
        plan, approved(plan), build_neutral_policy(created_at=NOW), "agent-executor"
    )

    assert receipt.outcome is Outcome.VERIFIED
    assert receipt.task_guid == "task_synthetic"
    assert receipt.api_request_id == "req-synthetic"
    assert gateway.mutations == 1
    assert exit_code_for_receipt(receipt) == 0
    record = ExecutionJournal(tmp_path / "journal").status(plan.plan_hash)
    assert record is not None and record.state is ExecutionState.VERIFIED


def test_readback_mismatch_is_partial_and_never_replayed(tmp_path: Path) -> None:
    plan = create_plan()
    gateway = StubGateway([TaskSnapshot(guid="task_synthetic", fields={"summary": "Different"})])
    service = executor(gateway, tmp_path / "journal")
    receipt = service.execute(
        plan, approved(plan), build_neutral_policy(created_at=NOW), "agent-executor"
    )
    assert receipt.outcome is Outcome.PARTIAL
    assert receipt.mismatches == ("summary",)
    assert exit_code_for_receipt(receipt) == 7
    with pytest.raises(ReplayBlockedError):
        service.execute(
            plan, approved(plan), build_neutral_policy(created_at=NOW), "agent-executor"
        )
    assert gateway.mutations == 1


def test_incremental_assign_with_existing_member_emits_verified_receipt(
    tmp_path: Path,
) -> None:
    existing = AssigneeRef(
        identifier_type=AssigneeIdentifierType.USER_ID,
        identifier="user_existing",
    )
    requested = AssigneeRef(
        identifier_type=AssigneeIdentifierType.USER_ID,
        identifier="user_requested",
    )
    before = TaskSnapshot(guid="task_synthetic", fields={}, assignees=(existing,))
    plan = PlanV1.build(
        created_at=NOW,
        tool_version=__version__,
        plan_id="plan_assign_synthetic",
        action=Action.ASSIGN,
        target=TaskTarget(task_guid="task_synthetic"),
        requested_fields={
            "assignees": [{"identifier_type": "user_id", "identifier": "user_requested"}]
        },
        assignees=(requested,),
        auth_context=AUTH,
        expires_at=NOW + timedelta(minutes=15),
        observed_before=before.to_state(),
        precondition_fingerprint=before.fingerprint(),
    )
    after = TaskSnapshot(guid="task_synthetic", fields={}, assignees=(existing, requested))
    gateway = StubGateway([before, after])

    receipt = executor(gateway, tmp_path).execute(
        plan, approved(plan), build_neutral_policy(created_at=NOW), "agent-executor"
    )

    assert receipt.outcome is Outcome.VERIFIED
    assert gateway.mutations == 1


def test_ambiguous_mutation_is_unknown_and_attempted_once(tmp_path: Path) -> None:
    plan = create_plan()
    gateway = StubGateway([])
    gateway.failure = FeishuTransportError(method="POST", retryable=False)
    receipt = executor(gateway, tmp_path / "journal").execute(
        plan, approved(plan), build_neutral_policy(created_at=NOW), "agent-executor"
    )
    assert receipt.outcome is Outcome.UNKNOWN
    assert exit_code_for_receipt(receipt) == 6
    assert gateway.mutations == 1
    record = ExecutionJournal(tmp_path / "journal").status(plan.plan_hash)
    assert record is not None and record.state is ExecutionState.UNKNOWN


def test_accepted_mutation_with_invalid_response_is_unknown(tmp_path: Path) -> None:
    plan = create_plan()
    gateway = StubGateway([])
    gateway.failure = FeishuResponseError("Feishu mutation response has an invalid shape")
    receipt = executor(gateway, tmp_path / "journal").execute(
        plan, approved(plan), build_neutral_policy(created_at=NOW), "agent-executor"
    )
    assert receipt.outcome is Outcome.UNKNOWN
    assert gateway.mutations == 1


def test_definitive_api_failure_is_failed(tmp_path: Path) -> None:
    plan = create_plan()
    gateway = StubGateway([])
    gateway.failure = FeishuAPIError(
        status_code=400, api_code=1470400, request_id="req-safe", retryable=False
    )
    receipt = executor(gateway, tmp_path / "journal").execute(
        plan, approved(plan), build_neutral_policy(created_at=NOW), "agent-executor"
    )
    assert receipt.outcome is Outcome.FAILED
    assert exit_code_for_receipt(receipt) == 5
    assert gateway.mutations == 1


@pytest.mark.parametrize("status_code", [408, 500, 502, 503, 504])
def test_ambiguous_mutation_http_failure_is_unknown(tmp_path: Path, status_code: int) -> None:
    plan = create_plan()
    gateway = StubGateway([])
    gateway.failure = FeishuAPIError(
        status_code=status_code,
        api_code=1470500,
        request_id="req-safe",
        retryable=False,
    )

    receipt = executor(gateway, tmp_path / "journal").execute(
        plan, approved(plan), build_neutral_policy(created_at=NOW), "agent-executor"
    )

    assert receipt.outcome is Outcome.UNKNOWN
    assert exit_code_for_receipt(receipt) == 6
    record = ExecutionJournal(tmp_path / "journal").status(plan.plan_hash)
    assert record is not None and record.state is ExecutionState.UNKNOWN


def test_readback_failure_after_accepted_mutation_is_unknown_and_not_replayable(
    tmp_path: Path,
) -> None:
    plan = create_plan()
    gateway = StubGateway([])
    gateway.get_failure = FeishuTransportError(method="GET", retryable=True)
    service = executor(gateway, tmp_path / "journal")

    receipt = service.execute(
        plan, approved(plan), build_neutral_policy(created_at=NOW), "agent-executor"
    )

    assert receipt.outcome is Outcome.UNKNOWN
    assert receipt.task_guid == "task_synthetic"
    record = ExecutionJournal(tmp_path / "journal").status(plan.plan_hash)
    assert record is not None and record.state is ExecutionState.UNKNOWN
    with pytest.raises(Exception, match="unknown"):
        service.execute(
            plan, approved(plan), build_neutral_policy(created_at=NOW), "agent-executor"
        )
    assert gateway.mutations == 1


def test_auth_context_mismatch_fails_before_journal_or_mutation(tmp_path: Path) -> None:
    plan = create_plan()
    gateway = StubGateway([])
    other = build_auth_context(
        api_origin="https://open.feishu.cn",
        app_id="cli_other",
        tenant_id="tenant_synthetic",
        account_id="account_synthetic",
        actor_id="actor_synthetic",
    )
    with pytest.raises(AuthContextMismatchError):
        executor(gateway, tmp_path / "journal", other).execute(
            plan, approved(plan), build_neutral_policy(created_at=NOW), "agent-executor"
        )
    assert gateway.mutations == 0
    assert ExecutionJournal(tmp_path / "journal").status(plan.plan_hash) is None


def test_unresolved_error_finding_fails_before_auth_network_or_journal(tmp_path: Path) -> None:
    values = create_plan().model_dump(exclude={"plan_hash"})
    values["validation_findings"] = (
        ValidationFinding(
            code="synthetic_error",
            severity=FindingSeverity.ERROR,
            message="must not execute",
        ),
    )
    plan = PlanV1.build(**values)
    gateway = StubGateway([])
    auth_calls = 0

    def resolve_auth() -> AuthContext:
        nonlocal auth_calls
        auth_calls += 1
        return AUTH

    service = Executor(
        gateway,
        auth_context_resolver=resolve_auth,
        journal=ExecutionJournal(tmp_path / "journal"),
        now=lambda: NOW + timedelta(seconds=2),
    )

    with pytest.raises(PolicyRejectedError, match="validation errors"):
        service.execute(
            plan,
            approved(plan),
            build_neutral_policy(created_at=NOW),
            "agent-executor",
        )

    assert auth_calls == 0
    assert gateway.mutations == 0
    assert ExecutionJournal(tmp_path / "journal").status(plan.plan_hash) is None


def test_precondition_drift_fails_before_journal_or_mutation(tmp_path: Path) -> None:
    before = TaskSnapshot(guid="task_synthetic", fields={"summary": "Before"})
    plan = existing_plan(before)
    gateway = StubGateway([TaskSnapshot(guid="task_synthetic", fields={"summary": "Changed"})])
    with pytest.raises(PreconditionChangedError):
        executor(gateway, tmp_path / "journal").execute(
            plan, approved(plan), build_neutral_policy(created_at=NOW), "agent-executor"
        )
    assert gateway.mutations == 0
    assert ExecutionJournal(tmp_path / "journal").status(plan.plan_hash) is None


def test_changed_review_is_rejected_before_auth_resolution(tmp_path: Path) -> None:
    plan = create_plan()
    review = approved(plan).model_copy(update={"plan_hash": "f" * 64})
    called = False

    def auth() -> AuthContext:
        nonlocal called
        called = True
        return AUTH

    with pytest.raises(ArtifactIntegrityError):
        service = Executor(
            StubGateway([]),
            auth_context_resolver=auth,
            journal=ExecutionJournal(tmp_path),
        )
        service.execute(plan, review, build_neutral_policy(created_at=NOW), "agent-executor")
    assert not called


def test_policy_rejection_maps_to_exit_4_without_journal_or_mutation(tmp_path: Path) -> None:
    plan = create_plan()
    review = build_review(
        plan,
        "agent-reviewer",
        ReviewVerdict.REJECTED,
        intended_executor_id="agent-executor",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    gateway = StubGateway([])
    with pytest.raises(PolicyRejectedError) as caught:
        executor(gateway, tmp_path).execute(
            plan, review, build_neutral_policy(created_at=NOW), "agent-executor"
        )
    assert exit_code_for_error(caught.value) == 4
    assert gateway.mutations == 0
    assert ExecutionJournal(tmp_path).status(plan.plan_hash) is None


def test_tampered_plan_is_rejected_before_mutation(tmp_path: Path) -> None:
    plan = create_plan().model_copy(update={"requested_fields": {"summary": "Tampered"}})
    with pytest.raises(ArtifactIntegrityError):
        executor(StubGateway([]), tmp_path).execute(
            plan, approved(create_plan()), build_neutral_policy(created_at=NOW), "agent-executor"
        )


def test_base_exception_leaves_started_for_orphan_detection(tmp_path: Path) -> None:
    plan = create_plan()
    gateway = StubGateway([])
    gateway.failure = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        executor(gateway, tmp_path).execute(
            plan, approved(plan), build_neutral_policy(created_at=NOW), "agent-executor"
        )
    assert ExecutionJournal(tmp_path).status(plan.plan_hash).state is ExecutionState.STARTED  # type: ignore[union-attr]
