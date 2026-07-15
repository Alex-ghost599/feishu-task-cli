from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeGuard

from feishu_task_cli.artifacts.base import JsonValueNoFloat
from feishu_task_cli.artifacts.canonical import canonical_bytes
from feishu_task_cli.artifacts.plan import AssigneeIdentifierType, AssigneeRef
from feishu_task_cli.errors import FeishuResponseError
from feishu_task_cli.feishu.client import FeishuClient

TASK_FIELDS = ("completed_at", "description", "due", "summary")
SAFE_TASK_GUID = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def _is_safe_task_guid(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and SAFE_TASK_GUID.fullmatch(value) is not None


@dataclass(frozen=True)
class TaskSnapshot:
    guid: str
    fields: dict[str, JsonValueNoFloat]
    assignees: tuple[AssigneeRef, ...] = ()

    def __post_init__(self) -> None:
        if not _is_safe_task_guid(self.guid):
            raise ValueError("task_guid must be one safe URL path segment")

    def to_state(self) -> dict[str, JsonValueNoFloat]:
        state: dict[str, JsonValueNoFloat] = dict(self.fields)
        state["guid"] = self.guid
        state["assignees"] = [
            {
                "identifier_type": assignee.identifier_type.value,
                "identifier": assignee.identifier,
            }
            for assignee in self.assignees
        ]
        return state

    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_bytes(self.to_state())).hexdigest()


@dataclass(frozen=True)
class MutationResult:
    task_guid: str
    request_id: str | None = None


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise FeishuResponseError(f"Feishu {label} response has an invalid shape")
    return value


class TaskGateway:
    """Narrow Task v2 adapter; raw Feishu shapes do not cross this boundary."""

    def __init__(self, client: FeishuClient) -> None:
        self._client = client

    @staticmethod
    def _task_path(task_guid: str, suffix: str = "") -> str:
        if not SAFE_TASK_GUID.fullmatch(task_guid):
            raise ValueError("task_guid must be one safe URL path segment")
        return f"/open-apis/task/v2/tasks/{task_guid}{suffix}"

    def _snapshot(
        self,
        payload: object,
        *,
        identifier_type: AssigneeIdentifierType,
        expected_guid: str,
    ) -> TaskSnapshot:
        data = _mapping(payload, "Task")
        task = _mapping(data.get("task"), "Task")
        guid = task.get("guid")
        if not _is_safe_task_guid(guid):
            raise FeishuResponseError("Feishu Task response contains an unsafe task guid")
        if guid != expected_guid:
            raise FeishuResponseError("Feishu Task response guid does not match requested guid")
        fields: dict[str, JsonValueNoFloat] = {}
        for name in TASK_FIELDS:
            value = task.get(name)
            if name in task and (value is None or isinstance(value, (str, int, bool, list, dict))):
                fields[name] = value
        assignees: list[AssigneeRef] = []
        members = task.get("members", [])
        if isinstance(members, list):
            for member in members:
                if not isinstance(member, Mapping):
                    continue
                identifier = member.get("id")
                if (
                    member.get("type") == "user"
                    and member.get("role") == "assignee"
                    and isinstance(identifier, str)
                    and identifier.strip()
                ):
                    assignees.append(
                        AssigneeRef(identifier_type=identifier_type, identifier=identifier)
                    )
        return TaskSnapshot(guid=guid, fields=fields, assignees=tuple(assignees))

    def get(
        self,
        task_guid: str,
        *,
        identifier_type: AssigneeIdentifierType = AssigneeIdentifierType.OPEN_ID,
    ) -> TaskSnapshot:
        payload = self._client.request(
            "GET",
            self._task_path(task_guid),
            params={"user_id_type": identifier_type.value},
        )
        return self._snapshot(
            payload,
            identifier_type=identifier_type,
            expected_guid=task_guid,
        )

    @staticmethod
    def _members(assignees: Sequence[AssigneeRef]) -> tuple[str, list[dict[str, str]]]:
        if not assignees:
            return AssigneeIdentifierType.OPEN_ID.value, []
        kinds = {item.identifier_type for item in assignees}
        if len(kinds) != 1:
            raise ValueError("one mutation cannot mix assignee identifier types")
        kind = next(iter(kinds)).value
        return kind, [
            {"type": "user", "id": item.identifier, "role": "assignee"} for item in assignees
        ]

    @staticmethod
    def _result(payload: object, request_id: str | None) -> MutationResult:
        task = _mapping(_mapping(payload, "mutation").get("task"), "mutation")
        guid = task.get("guid")
        if not _is_safe_task_guid(guid):
            raise FeishuResponseError("Feishu mutation response contains an unsafe task guid")
        return MutationResult(task_guid=guid, request_id=request_id)

    def create(
        self,
        requested_fields: Mapping[str, JsonValueNoFloat],
        assignees: Sequence[AssigneeRef] = (),
        *,
        tasklist_guid: str | None = None,
    ) -> MutationResult:
        identifier_type, members = self._members(assignees)
        body: dict[str, object] = dict(requested_fields)
        if members:
            body["members"] = members
        if tasklist_guid is not None:
            body["tasklists"] = [{"tasklist_guid": tasklist_guid}]
        response = self._client.request_with_metadata(
            "POST",
            "/open-apis/task/v2/tasks",
            params={"user_id_type": identifier_type},
            json=body,
        )
        return self._result(response.data, response.request_id)

    def update(
        self, task_guid: str, requested_fields: Mapping[str, JsonValueNoFloat]
    ) -> MutationResult:
        fields = dict(requested_fields)
        response = self._client.request_with_metadata(
            "PATCH",
            self._task_path(task_guid),
            json={"task": fields, "update_fields": sorted(fields)},
        )
        return self._result(response.data, response.request_id)

    def assign(self, task_guid: str, assignees: Sequence[AssigneeRef]) -> MutationResult:
        identifier_type, members = self._members(assignees)
        response = self._client.request_with_metadata(
            "POST",
            self._task_path(task_guid, "/add_members"),
            params={"user_id_type": identifier_type},
            json={"members": members},
        )
        return self._result(response.data, response.request_id)

    def complete(self, task_guid: str, completed_at: str) -> MutationResult:
        return self.update(task_guid, {"completed_at": completed_at})
