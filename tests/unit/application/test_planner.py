from __future__ import annotations

from datetime import UTC, datetime

import pytest

from feishu_task_cli.application.planner import Planner, parse_assignee
from feishu_task_cli.artifacts.plan import Action, AssigneeIdentifierType
from feishu_task_cli.auth.context import build_auth_context
from feishu_task_cli.feishu.tasks import TaskSnapshot

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
AUTH = build_auth_context(
    api_origin="https://open.feishu.cn",
    app_id="cli_synthetic",
    tenant_id="tenant_synthetic",
    account_id="account_synthetic",
    actor_id="actor_synthetic",
)


class StubGateway:
    def __init__(self, snapshot: TaskSnapshot) -> None:
        self.snapshot = snapshot
        self.get_calls: list[str] = []
        self.identifier_types: list[AssigneeIdentifierType] = []

    def get(
        self,
        task_guid: str,
        *,
        identifier_type: AssigneeIdentifierType = AssigneeIdentifierType.OPEN_ID,
    ) -> TaskSnapshot:
        self.get_calls.append(task_guid)
        self.identifier_types.append(identifier_type)
        return self.snapshot


@pytest.mark.parametrize(
    ("value", "identifier_type"),
    [
        ("open_id:ou_synthetic", AssigneeIdentifierType.OPEN_ID),
        ("user_id:user_synthetic", AssigneeIdentifierType.USER_ID),
        ("union_id:on_synthetic", AssigneeIdentifierType.UNION_ID),
    ],
)
def test_parse_assignee_requires_typed_authoritative_identifier(
    value: str, identifier_type: AssigneeIdentifierType
) -> None:
    parsed = parse_assignee(value)
    assert parsed.identifier_type is identifier_type
    assert parsed.identifier == value.split(":", 1)[1]


@pytest.mark.parametrize("value", ["Synthetic User", "email:user@example.invalid", "open_id:"])
def test_parse_assignee_rejects_names_and_unknown_identifier_types(value: str) -> None:
    with pytest.raises(ValueError, match="typed assignee"):
        parse_assignee(value)


def test_create_plan_binds_auth_without_remote_precondition() -> None:
    gateway = StubGateway(TaskSnapshot(guid="unused", fields={}))
    planner = Planner(gateway, AUTH, now=lambda: NOW, id_factory=lambda: "plan_create")

    plan = planner.create(
        requested_fields={"summary": "Synthetic task"},
        tasklist_guid="tasklist_synthetic",
        assignees=("open_id:ou_synthetic",),
    )

    assert plan.action is Action.CREATE
    assert plan.auth_context == AUTH
    assert plan.observed_before is None
    assert plan.precondition_fingerprint is None
    assert gateway.get_calls == []


@pytest.mark.parametrize("requested_fields", [{}, {"summary": ""}, {"summary": "   "}])
def test_create_requires_non_empty_summary_before_network(
    requested_fields: dict[str, object],
) -> None:
    gateway = StubGateway(TaskSnapshot(guid="unused", fields={}))
    planner = Planner(gateway, AUTH, now=lambda: NOW)

    with pytest.raises(ValueError, match="summary"):
        planner.create(
            requested_fields=requested_fields,
            tasklist_guid="tasklist_synthetic",
        )
    assert gateway.get_calls == []


def test_update_requires_at_least_one_field_before_network() -> None:
    gateway = StubGateway(TaskSnapshot(guid="task_synthetic", fields={}))
    planner = Planner(gateway, AUTH, now=lambda: NOW)

    with pytest.raises(ValueError, match="at least one"):
        planner.update("task_synthetic", {})
    assert gateway.get_calls == []


def test_planner_normalizes_task_timestamps_and_due() -> None:
    gateway = StubGateway(TaskSnapshot(guid="unused", fields={}))
    planner = Planner(gateway, AUTH, now=lambda: NOW)

    plan = planner.create(
        requested_fields={
            "summary": "Synthetic task",
            "completed_at": 1735787045000,
            "due": {"timestamp": 1735873445000, "is_all_day": False},
        },
        tasklist_guid="tasklist_synthetic",
    )

    assert plan.requested_fields["completed_at"] == "1735787045000"
    assert plan.requested_fields["due"] == {
        "timestamp": "1735873445000",
        "is_all_day": False,
    }


@pytest.mark.parametrize(
    "requested_fields",
    [
        {"summary": 7},
        {"summary": "x" * 3001},
        {"summary": "Synthetic task", "description": "x" * 3001},
        {"summary": "Synthetic task", "completed_at": -1},
        {"summary": "Synthetic task", "completed_at": "not-a-timestamp"},
        {"summary": "Synthetic task", "due": {"timestamp": "1"}},
        {
            "summary": "Synthetic task",
            "due": {"timestamp": "1", "is_all_day": "false"},
        },
    ],
)
def test_planner_rejects_invalid_task_field_values(
    requested_fields: dict[str, object],
) -> None:
    gateway = StubGateway(TaskSnapshot(guid="unused", fields={}))
    planner = Planner(gateway, AUTH, now=lambda: NOW)

    with pytest.raises(ValueError):
        planner.create(
            requested_fields=requested_fields,
            tasklist_guid="tasklist_synthetic",
        )
    assert gateway.get_calls == []


def test_assignees_are_trimmed_deduplicated_and_limited() -> None:
    gateway = StubGateway(TaskSnapshot(guid="unused", fields={}))
    planner = Planner(gateway, AUTH, now=lambda: NOW)

    plan = planner.create(
        requested_fields={"summary": "Synthetic task"},
        tasklist_guid="tasklist_synthetic",
        assignees=("open_id:  ou_synthetic  ", "open_id:ou_synthetic"),
    )

    assert [item.identifier for item in plan.assignees] == ["ou_synthetic"]

    with pytest.raises(ValueError, match="at most 50"):
        planner.create(
            requested_fields={"summary": "Synthetic task"},
            tasklist_guid="tasklist_synthetic",
            assignees=tuple(f"open_id:ou_{index}" for index in range(51)),
        )


def test_assignee_rejects_identifier_with_internal_whitespace() -> None:
    with pytest.raises(ValueError, match="whitespace"):
        parse_assignee("open_id:ou synthetic")


def test_planner_rejects_fields_outside_v01_task_scope() -> None:
    gateway = StubGateway(TaskSnapshot(guid="unused", fields={}))
    planner = Planner(gateway, AUTH, now=lambda: NOW)

    with pytest.raises(ValueError, match="unsupported Task fields"):
        planner.create(
            requested_fields={"owner": "unexpected"},
            tasklist_guid="tasklist_synthetic",
        )
    assert gateway.get_calls == []


@pytest.mark.parametrize("method", ["update", "assign", "complete"])
def test_existing_task_plans_bind_observed_state_and_precondition(method: str) -> None:
    before = TaskSnapshot(
        guid="task_synthetic",
        fields={"summary": "Before", "completed_at": "0"},
        assignees=(),
    )
    gateway = StubGateway(before)
    planner = Planner(gateway, AUTH, now=lambda: NOW, id_factory=lambda: f"plan_{method}")

    if method == "update":
        plan = planner.update("task_synthetic", {"summary": "After"})
    elif method == "assign":
        plan = planner.assign("task_synthetic", ("user_id:user_synthetic",))
    else:
        plan = planner.complete("task_synthetic")

    assert plan.action.value == method
    assert plan.observed_before == before.to_state()
    assert plan.precondition_fingerprint == before.fingerprint()
    assert gateway.get_calls == ["task_synthetic"]
    expected_type = (
        AssigneeIdentifierType.USER_ID if method == "assign" else AssigneeIdentifierType.OPEN_ID
    )
    assert gateway.identifier_types == [expected_type]
