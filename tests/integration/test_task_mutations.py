from __future__ import annotations

import json

import httpx
import pytest

from feishu_task_cli.artifacts.plan import AssigneeIdentifierType, AssigneeRef
from feishu_task_cli.errors import FeishuResponseError
from feishu_task_cli.feishu.client import FeishuClient
from feishu_task_cli.feishu.tasks import TaskGateway


@pytest.mark.parametrize(
    ("operation", "method", "path"),
    [
        ("create", "POST", "/open-apis/task/v2/tasks"),
        ("update", "PATCH", "/open-apis/task/v2/tasks/task_synthetic"),
        ("assign", "POST", "/open-apis/task/v2/tasks/task_synthetic/add_members"),
        ("complete", "PATCH", "/open-apis/task/v2/tasks/task_synthetic"),
    ],
)
def test_task_mutations_use_one_request_and_return_guid(
    operation: str, method: str, path: str
) -> None:
    requests: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"x-request-id": "req-synthetic-success"},
            json={"code": 0, "data": {"task": {"guid": "task_synthetic"}}},
        )

    client = FeishuClient(
        api_origin="https://open.feishu.cn",
        access_token="synthetic-access-token-value",
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )
    gateway = TaskGateway(client)
    assignees = (
        AssigneeRef(
            identifier_type=AssigneeIdentifierType.USER_ID,
            identifier="user_synthetic",
        ),
    )

    if operation == "create":
        result = gateway.create(
            {"summary": "Synthetic"}, assignees, tasklist_guid="tasklist_synthetic"
        )
    elif operation == "update":
        result = gateway.update("task_synthetic", {"summary": "Updated"})
    elif operation == "assign":
        result = gateway.assign("task_synthetic", assignees)
    else:
        result = gateway.complete("task_synthetic", "1735787045000")

    assert result.task_guid == "task_synthetic"
    assert result.request_id == "req-synthetic-success"
    assert len(requests) == 1
    assert requests[0].method == method
    assert requests[0].url.path == path
    body = json.loads(requests[0].content)
    if operation == "update":
        assert body == {"task": {"summary": "Updated"}, "update_fields": ["summary"]}
    if operation == "assign":
        assert requests[0].url.params["user_id_type"] == "user_id"
        assert body["members"] == [{"type": "user", "id": "user_synthetic", "role": "assignee"}]


def test_gateway_rejects_mixed_assignee_types_before_network() -> None:
    client = FeishuClient(
        api_origin="https://open.feishu.cn",
        access_token="synthetic-access-token-value",
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda request: pytest.fail("network must not be called"))
        ),
    )
    assignees = (
        AssigneeRef(identifier_type=AssigneeIdentifierType.OPEN_ID, identifier="ou_a"),
        AssigneeRef(identifier_type=AssigneeIdentifierType.USER_ID, identifier="user_b"),
    )
    with pytest.raises(ValueError, match="mix"):
        TaskGateway(client).assign("task_synthetic", assignees)


def test_accepted_mutation_without_returned_guid_is_typed_ambiguous_response() -> None:
    client = FeishuClient(
        api_origin="https://open.feishu.cn",
        access_token="synthetic-access-token-value",
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"code": 0, "data": {}})
            )
        ),
    )
    with pytest.raises(FeishuResponseError, match="invalid shape"):
        TaskGateway(client).create({"summary": "Synthetic"})
