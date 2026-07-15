from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from feishu_task_cli import __version__
from feishu_task_cli.application.policy_engine import validate_execution_review
from feishu_task_cli.application.reconcile import reconcile
from feishu_task_cli.artifacts.base import JsonValueNoFloat
from feishu_task_cli.artifacts.plan import Action, AssigneeIdentifierType, AuthContext, PlanV1
from feishu_task_cli.artifacts.policy import PolicyV1
from feishu_task_cli.artifacts.receipt import (
    DeclaredReviewRelationship,
    Outcome,
    ReceiptV1,
)
from feishu_task_cli.artifacts.review import ReviewV1
from feishu_task_cli.errors import (
    AuthContextMismatchError,
    FeishuResponseError,
    PolicyRejectedError,
    PreconditionChangedError,
)
from feishu_task_cli.feishu.client import FeishuAPIError, FeishuTransportError
from feishu_task_cli.feishu.tasks import MutationResult, TaskGateway
from feishu_task_cli.journal.store import ExecutionJournal, ExecutionState

EXIT_BY_OUTCOME = {
    Outcome.VERIFIED: 0,
    Outcome.REJECTED: 4,
    Outcome.FAILED: 5,
    Outcome.UNKNOWN: 6,
    Outcome.PARTIAL: 7,
}


def exit_code_for_receipt(receipt: ReceiptV1) -> int:
    return EXIT_BY_OUTCOME[receipt.outcome]


def exit_code_for_error(error: Exception) -> int:
    if isinstance(error, PolicyRejectedError):
        return 4
    raise ValueError("error does not have an execution exit-code mapping")


class Executor:
    def __init__(
        self,
        gateway: TaskGateway,
        *,
        auth_context_resolver: Callable[[], AuthContext],
        journal: ExecutionJournal,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._gateway = gateway
        self._resolve_auth_context = auth_context_resolver
        self._journal = journal
        self._now = now

    @staticmethod
    def _identifier_type(plan: PlanV1) -> AssigneeIdentifierType:
        return (
            plan.assignees[0].identifier_type if plan.assignees else AssigneeIdentifierType.OPEN_ID
        )

    @staticmethod
    def _requested_state(plan: PlanV1) -> dict[str, JsonValueNoFloat]:
        requested = dict(plan.requested_fields)
        if plan.assignees and "assignees" not in requested:
            requested["assignees"] = [
                {
                    "identifier_type": item.identifier_type.value,
                    "identifier": item.identifier,
                }
                for item in plan.assignees
            ]
        return requested

    def _mutate(self, plan: PlanV1) -> MutationResult:
        if plan.action is Action.CREATE:
            return self._gateway.create(
                plan.requested_fields,
                plan.assignees,
                tasklist_guid=plan.target.tasklist_guid,
            )
        assert plan.target.task_guid is not None
        if plan.action is Action.UPDATE:
            return self._gateway.update(plan.target.task_guid, plan.requested_fields)
        if plan.action is Action.ASSIGN:
            return self._gateway.assign(plan.target.task_guid, plan.assignees)
        completed_at = plan.requested_fields.get("completed_at")
        if not isinstance(completed_at, str):
            raise ValueError("complete plan requires a normalized completed_at timestamp")
        return self._gateway.complete(plan.target.task_guid, completed_at)

    def _receipt(
        self,
        *,
        plan: PlanV1,
        review: ReviewV1,
        executor_id: str,
        relationship: DeclaredReviewRelationship,
        started_at: datetime,
        outcome: Outcome,
        task_guid: str | None = None,
        observed_state: dict[str, JsonValueNoFloat] | None = None,
        mismatches: tuple[str, ...] = (),
        omitted_fields: tuple[str, ...] = (),
        request_id: str | None = None,
    ) -> ReceiptV1:
        return ReceiptV1.build(
            created_at=self._now(),
            tool_version=__version__,
            action=plan.action,
            plan_hash=plan.plan_hash,
            review_hash=review.review_hash,
            declared_review_relationship=relationship,
            reviewer_id=review.reviewer_id,
            executor_id=executor_id,
            auth_context=plan.auth_context,
            task_guid=task_guid,
            requested_state=self._requested_state(plan),
            observed_state=observed_state or {},
            mismatches=mismatches,
            omitted_fields=omitted_fields,
            api_request_id=request_id,
            started_at=started_at,
            completed_at=self._now(),
            outcome=outcome,
        )

    def execute(
        self,
        plan: PlanV1,
        review: ReviewV1,
        policy: PolicyV1,
        executor_id: str,
    ) -> ReceiptV1:
        # Artifact and declared-review validation intentionally precede token resolution.
        relationship = validate_execution_review(plan, review, policy, executor_id, now=self._now())
        actual_auth = self._resolve_auth_context()
        if actual_auth != plan.auth_context:
            raise AuthContextMismatchError("live AuthContext does not match the execution Plan")

        if plan.action is not Action.CREATE:
            assert plan.target.task_guid is not None
            before = self._gateway.get(
                plan.target.task_guid,
                identifier_type=self._identifier_type(plan),
            )
            if before.fingerprint() != plan.precondition_fingerprint:
                raise PreconditionChangedError("Task changed after the Plan was created")

        started = self._now()
        with self._journal.execution(plan.plan_hash) as attempt:
            try:
                result = self._mutate(plan)
            except (FeishuResponseError, FeishuTransportError):
                attempt.complete(ExecutionState.UNKNOWN)
                return self._receipt(
                    plan=plan,
                    review=review,
                    executor_id=executor_id,
                    relationship=relationship,
                    started_at=started,
                    outcome=Outcome.UNKNOWN,
                )
            except FeishuAPIError as error:
                attempt.complete(ExecutionState.FAILED)
                return self._receipt(
                    plan=plan,
                    review=review,
                    executor_id=executor_id,
                    relationship=relationship,
                    started_at=started,
                    outcome=Outcome.FAILED,
                    request_id=error.request_id,
                )

            try:
                observed = self._gateway.get(
                    result.task_guid,
                    identifier_type=self._identifier_type(plan),
                )
            except (FeishuAPIError, FeishuResponseError, FeishuTransportError):
                attempt.complete(ExecutionState.UNKNOWN)
                return self._receipt(
                    plan=plan,
                    review=review,
                    executor_id=executor_id,
                    relationship=relationship,
                    started_at=started,
                    outcome=Outcome.UNKNOWN,
                    task_guid=result.task_guid,
                    request_id=result.request_id,
                )
            observed_state = observed.to_state()
            comparison = reconcile(self._requested_state(plan), observed_state)
            guid_mismatch = (
                plan.target.task_guid is not None and result.task_guid != plan.target.task_guid
            )
            mismatches = comparison.mismatches + (("task_guid",) if guid_mismatch else ())
            outcome = (
                Outcome.VERIFIED
                if not mismatches and not comparison.omitted_fields
                else Outcome.PARTIAL
            )
            attempt.complete(
                ExecutionState.VERIFIED if outcome is Outcome.VERIFIED else ExecutionState.PARTIAL
            )
            return self._receipt(
                plan=plan,
                review=review,
                executor_id=executor_id,
                relationship=relationship,
                started_at=started,
                outcome=outcome,
                task_guid=result.task_guid,
                observed_state=observed_state,
                mismatches=mismatches,
                omitted_fields=comparison.omitted_fields,
                request_id=result.request_id,
            )
