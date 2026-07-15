from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta

from feishu_task_cli import __version__
from feishu_task_cli.artifacts.base import JsonValueNoFloat
from feishu_task_cli.artifacts.plan import (
    Action,
    AssigneeIdentifierType,
    AssigneeRef,
    AuthContext,
    PlanV1,
    TaskTarget,
)
from feishu_task_cli.artifacts.task_semantics import (
    normalize_assignee_pairs,
    normalize_task_fields,
)
from feishu_task_cli.feishu.tasks import TaskGateway


def parse_assignee(value: str, *, display_name: str | None = None) -> AssigneeRef:
    try:
        prefix, identifier = value.split(":", 1)
        identifier_type = AssigneeIdentifierType(prefix)
    except (ValueError, AttributeError):
        raise ValueError("typed assignee must use open_id:, user_id:, or union_id:") from None
    _, identifier = normalize_assignee_pairs(((identifier_type.value, identifier),))[0]
    return AssigneeRef(
        identifier_type=identifier_type,
        identifier=identifier,
        display_name=display_name,
    )


class Planner:
    def __init__(
        self,
        gateway: TaskGateway,
        auth_context: AuthContext,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
        ttl_seconds: int = 900,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._gateway = gateway
        self._auth_context = auth_context
        self._now = now
        self._id_factory = id_factory
        self._ttl_seconds = ttl_seconds

    def _base(self, action: Action, target: TaskTarget) -> dict[str, object]:
        created = self._now()
        return {
            "created_at": created,
            "tool_version": __version__,
            "plan_id": self._id_factory(),
            "action": action,
            "target": target,
            "auth_context": self._auth_context,
            "expires_at": created + timedelta(seconds=self._ttl_seconds),
            "required_scopes": ("task:task:write",),
        }

    @staticmethod
    def _assignees(values: Sequence[str]) -> tuple[AssigneeRef, ...]:
        parsed = tuple(parse_assignee(value) for value in values)
        normalized = normalize_assignee_pairs(
            tuple((item.identifier_type.value, item.identifier) for item in parsed)
        )
        return tuple(
            AssigneeRef(
                identifier_type=AssigneeIdentifierType(identifier_type),
                identifier=identifier,
            )
            for identifier_type, identifier in normalized
        )

    def create(
        self,
        *,
        requested_fields: Mapping[str, JsonValueNoFloat],
        tasklist_guid: str,
        assignees: Sequence[str] = (),
    ) -> PlanV1:
        return PlanV1.build(
            **self._base(Action.CREATE, TaskTarget(tasklist_guid=tasklist_guid)),
            requested_fields=normalize_task_fields(Action.CREATE.value, requested_fields),
            assignees=self._assignees(assignees),
        )

    def _existing(
        self,
        action: Action,
        task_guid: str,
        *,
        requested_fields: Mapping[str, JsonValueNoFloat],
        assignees: Sequence[str] = (),
    ) -> PlanV1:
        normalized_fields = normalize_task_fields(action.value, requested_fields)
        before = self._gateway.get(task_guid)
        return PlanV1.build(
            **self._base(action, TaskTarget(task_guid=task_guid)),
            requested_fields=normalized_fields,
            assignees=self._assignees(assignees),
            observed_before=before.to_state(),
            precondition_fingerprint=before.fingerprint(),
        )

    def update(self, task_guid: str, requested_fields: Mapping[str, JsonValueNoFloat]) -> PlanV1:
        return self._existing(Action.UPDATE, task_guid, requested_fields=requested_fields)

    def assign(self, task_guid: str, assignees: Sequence[str]) -> PlanV1:
        parsed = self._assignees(assignees)
        if not parsed:
            raise ValueError("assign plan requires at least one typed assignee")
        requested: dict[str, JsonValueNoFloat] = {
            "assignees": [
                {
                    "identifier_type": item.identifier_type.value,
                    "identifier": item.identifier,
                }
                for item in parsed
            ]
        }
        before = self._gateway.get(task_guid, identifier_type=parsed[0].identifier_type)
        return PlanV1.build(
            **self._base(Action.ASSIGN, TaskTarget(task_guid=task_guid)),
            requested_fields=requested,
            assignees=parsed,
            observed_before=before.to_state(),
            precondition_fingerprint=before.fingerprint(),
        )

    def complete(self, task_guid: str) -> PlanV1:
        completed_at = str(int(self._now().timestamp() * 1000))
        return self._existing(
            Action.COMPLETE,
            task_guid,
            requested_fields={"completed_at": completed_at},
        )
