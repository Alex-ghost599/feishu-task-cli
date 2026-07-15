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
from feishu_task_cli.feishu.tasks import TaskGateway

ALLOWED_TASK_FIELDS = frozenset({"completed_at", "description", "due", "summary"})
MAX_TASK_TEXT_LENGTH = 3000
MAX_ASSIGNEES = 50


def _normalize_timestamp(value: object, *, field_name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{field_name} must be a millisecond timestamp")
    normalized = str(value)
    if not normalized.isdigit() or len(normalized) > 20:
        raise ValueError(f"{field_name} must be a non-negative millisecond timestamp")
    return normalized


def _validate_fields(
    values: Mapping[str, JsonValueNoFloat],
    *,
    require_summary: bool = False,
    require_nonempty: bool = False,
) -> dict[str, JsonValueNoFloat]:
    fields = dict(values)
    unsupported = sorted(set(fields).difference(ALLOWED_TASK_FIELDS))
    if unsupported:
        raise ValueError(f"unsupported Task fields: {', '.join(unsupported)}")

    if require_nonempty and not fields:
        raise ValueError("update requires at least one Task field")
    if require_summary and "summary" not in fields:
        raise ValueError("create requires summary")

    summary = fields.get("summary")
    if "summary" in fields and (
        not isinstance(summary, str) or not summary.strip() or len(summary) > MAX_TASK_TEXT_LENGTH
    ):
        raise ValueError("summary must be a non-empty string of at most 3000 characters")

    description = fields.get("description")
    if "description" in fields and (
        not isinstance(description, str) or len(description) > MAX_TASK_TEXT_LENGTH
    ):
        raise ValueError("description must be a string of at most 3000 characters")

    if "completed_at" in fields:
        fields["completed_at"] = _normalize_timestamp(
            fields["completed_at"], field_name="completed_at"
        )

    if "due" in fields:
        due = fields["due"]
        if not isinstance(due, Mapping) or set(due) != {"timestamp", "is_all_day"}:
            raise ValueError("due must contain exactly timestamp and is_all_day")
        is_all_day = due["is_all_day"]
        if not isinstance(is_all_day, bool):
            raise ValueError("due.is_all_day must be a boolean")
        fields["due"] = {
            "timestamp": _normalize_timestamp(due["timestamp"], field_name="due.timestamp"),
            "is_all_day": is_all_day,
        }
    return fields


def parse_assignee(value: str, *, display_name: str | None = None) -> AssigneeRef:
    try:
        prefix, identifier = value.split(":", 1)
        identifier_type = AssigneeIdentifierType(prefix)
    except (ValueError, AttributeError):
        raise ValueError("typed assignee must use open_id:, user_id:, or union_id:") from None
    identifier = identifier.strip()
    if not identifier:
        raise ValueError("typed assignee identifier must be non-empty")
    if any(character.isspace() for character in identifier):
        raise ValueError("typed assignee identifier must not contain whitespace")
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
        if len({item.identifier_type for item in parsed}) > 1:
            raise ValueError("one plan cannot mix assignee identifier types")
        deduplicated = tuple(
            dict.fromkeys((item.identifier_type, item.identifier) for item in parsed)
        )
        if len(deduplicated) > MAX_ASSIGNEES:
            raise ValueError("one plan can contain at most 50 unique assignees")
        return tuple(
            AssigneeRef(identifier_type=identifier_type, identifier=identifier)
            for identifier_type, identifier in deduplicated
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
            requested_fields=_validate_fields(requested_fields, require_summary=True),
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
        normalized_fields = _validate_fields(
            requested_fields,
            require_nonempty=action is Action.UPDATE,
        )
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
