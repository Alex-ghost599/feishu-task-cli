from __future__ import annotations

import httpx
import pytest

from feishu_task_cli.errors import FeishuResponseError
from feishu_task_cli.feishu.client import FeishuClient
from feishu_task_cli.feishu.tasks import TaskGateway, TaskSnapshot


def test_task_get_normalizes_raw_feishu_payload() -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/open-apis/task/v2/tasks/task_synthetic"
        assert request.url.params["user_id_type"] == "open_id"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "task": {
                        "guid": "task_synthetic",
                        "summary": "Synthetic task",
                        "completed_at": "0",
                        "members": [
                            {"type": "user", "id": "ou_synthetic", "role": "assignee"},
                            {"type": "user", "id": "ou_follower", "role": "follower"},
                        ],
                    }
                },
            },
        )

    client = FeishuClient(
        api_origin="https://open.feishu.cn",
        access_token="synthetic-access-token-value",
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )
    task = TaskGateway(client).get("task_synthetic")

    assert task.guid == "task_synthetic"
    assert task.fields == {"completed_at": "0", "summary": "Synthetic task"}
    assert [item.identifier for item in task.assignees] == ["ou_synthetic"]


def test_task_get_rejects_response_for_a_different_guid() -> None:
    client = FeishuClient(
        api_origin="https://open.feishu.cn",
        access_token="synthetic-access-token-value",
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"code": 0, "data": {"task": {"guid": "task_other"}}},
                )
            )
        ),
    )

    with pytest.raises(FeishuResponseError, match="does not match requested guid"):
        TaskGateway(client).get("task_synthetic")


def test_task_snapshot_fingerprint_binds_guid() -> None:
    first = TaskSnapshot(guid="task_first", fields={"summary": "Same"})
    second = TaskSnapshot(guid="task_second", fields={"summary": "Same"})

    assert first.fingerprint() != second.fingerprint()
    assert first.to_state()["guid"] == "task_first"


@pytest.mark.parametrize(
    "task_guid",
    ["../tasks/other", "task?x=1", "task/child", "", "x" * 101],
)
def test_task_guid_must_be_one_safe_path_segment(task_guid: str) -> None:
    client = FeishuClient(
        api_origin="https://open.feishu.cn",
        access_token="synthetic-access-token-value",
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda request: pytest.fail("network must not be called"))
        ),
    )
    with pytest.raises(ValueError, match="task_guid"):
        TaskGateway(client).get(task_guid)
