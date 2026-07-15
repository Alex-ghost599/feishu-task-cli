from __future__ import annotations

import logging

import httpx
import pytest

from feishu_task_cli.feishu.client import (
    FeishuAPIError,
    FeishuClient,
    FeishuTransportError,
    redact,
)


def _secret(label: str) -> str:
    return f"synthetic-{label}-" + "z" * 24


def test_recursive_redaction_covers_headers_json_text_logs_and_debug_hook(
    caplog: pytest.LogCaptureFixture,
) -> None:
    access = _secret("access")
    nested = _secret("nested")
    events: list[object] = []

    def transport(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {access}"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "refresh_token": nested,
                    "message": f"Authorization: Bearer {nested}",
                },
            },
        )

    client = FeishuClient(
        api_origin="https://open.feishu.cn",
        access_token=access,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
        debug_hook=events.append,
    )

    with caplog.at_level(logging.DEBUG, logger="feishu_task_cli.feishu.client"):
        response = client.request("GET", "/open-apis/task/v2/tasks/synthetic")

    rendered = repr((response, events, caplog.text, client))
    assert access not in rendered
    assert nested not in rendered
    assert events == [
        {"phase": "request", "method": "GET", "attempt": 1},
        {"phase": "response", "method": "GET", "status_code": 200, "request_id": None},
    ]
    assert "Feishu HTTP event payload: [REDACTED]" in caplog.text
    assert "Authorization" not in caplog.text
    assert "refresh_token" not in caplog.text


def test_redact_recursively_preserves_non_secret_structure() -> None:
    secret = _secret("body")

    value = redact(
        {
            "items": [{"access_token": secret, "count": 2}],
            "message": f"Bearer {secret}",
            "ok": True,
        }
    )

    assert value == {
        "items": [{"access_token": "[REDACTED]", "count": 2}],
        "message": "Bearer [REDACTED]",
        "ok": True,
    }


def test_api_error_is_typed_redacted_and_accepts_only_safe_request_id() -> None:
    secret = _secret("remote")

    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            headers={"x-request-id": f"Bearer {secret}"},
            json={"code": 1234, "msg": secret, "request_id": secret},
        )

    client = FeishuClient(
        api_origin="https://open.feishu.cn",
        access_token=_secret("access"),
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )

    with pytest.raises(FeishuAPIError) as caught:
        client.request("GET", "/open-apis/task/v2/tasks/synthetic")

    assert caught.value.status_code == 400
    assert caught.value.api_code == 1234
    assert caught.value.request_id is None
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)


def test_custom_headers_are_rejected_before_transport() -> None:
    api_key = _secret("api-key")
    calls = 0

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    client = FeishuClient(
        api_origin="https://open.feishu.cn",
        access_token=_secret("access"),
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )

    with pytest.raises(ValueError, match="custom headers") as caught:
        client.request("GET", "/synthetic", headers={"X-Api-Key": api_key})
    assert calls == 0
    assert api_key not in repr(caught.value)


def test_request_id_is_never_read_from_response_body() -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": 1234, "request_id": "req-body-001"})

    client = FeishuClient(
        api_origin="https://open.feishu.cn",
        access_token=_secret("access"),
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
        max_get_attempts=1,
    )

    with pytest.raises(FeishuAPIError) as caught:
        client.request("GET", "/synthetic")
    assert caught.value.request_id is None


def test_request_id_cannot_echo_secret_from_request_body() -> None:
    secret = _secret("body-echo")

    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, headers={"x-request-id": secret}, json={"code": 1234})

    client = FeishuClient(
        api_origin="https://open.feishu.cn",
        access_token=_secret("access"),
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
        max_get_attempts=1,
    )

    with pytest.raises(FeishuAPIError) as caught:
        client.request("GET", "/synthetic", json={"opaque": secret})
    assert caught.value.request_id is None
    assert secret not in repr(caught.value)


@pytest.mark.parametrize(
    "origin",
    ["http://open.feishu.cn", "https://evil.example", "https://open.feishu.cn/path"],
)
def test_feishu_client_rejects_nonofficial_origin(origin: str) -> None:
    with pytest.raises(ValueError, match="official Feishu API origin"):
        FeishuClient(api_origin=origin, access_token=_secret("access"))


def test_safe_request_id_is_retained() -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, headers={"x-request-id": "req-synthetic-001"})

    client = FeishuClient(
        api_origin="https://open.feishu.cn",
        access_token=_secret("access"),
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
        max_get_attempts=1,
    )

    with pytest.raises(FeishuAPIError) as caught:
        client.request("GET", "/synthetic")
    assert caught.value.request_id == "req-synthetic-001"


def test_get_retries_bounded_transport_failure() -> None:
    attempts = 0
    sleeps: list[float] = []

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(200, json={"code": 0, "data": {"ok": True}})

    client = FeishuClient(
        api_origin="https://open.feishu.cn",
        access_token=_secret("access"),
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
        max_get_attempts=3,
        sleep=sleeps.append,
        backoff_base=0.25,
    )

    assert client.request("GET", "/synthetic") == {"ok": True}
    assert attempts == 3
    assert sleeps == [0.25, 0.5]


def test_get_retries_bounded_retryable_status() -> None:
    attempts = 0

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"code": 0, "data": {"ok": True}})

    client = FeishuClient(
        api_origin="https://open.feishu.cn",
        access_token=_secret("access"),
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )

    assert client.request("GET", "/synthetic") == {"ok": True}
    assert attempts == 2


def test_get_honors_bounded_retry_after() -> None:
    attempts = 0
    sleeps: list[float] = []

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "999999"})
        return httpx.Response(200, json={"code": 0, "data": {"ok": True}})

    client = FeishuClient(
        api_origin="https://open.feishu.cn",
        access_token=_secret("access"),
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
        sleep=sleeps.append,
        retry_after_cap=10,
    )

    assert client.request("GET", "/synthetic") == {"ok": True}
    assert sleeps == [10]


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout])
def test_mutation_transport_is_attempted_once(
    failure: type[httpx.TransportError],
) -> None:
    attempts = 0
    secret = _secret("exception")

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise failure(secret, request=request)

    client = FeishuClient(
        api_origin="https://open.feishu.cn",
        access_token=_secret("access"),
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )

    with pytest.raises(FeishuTransportError) as caught:
        client.request("POST", "/synthetic", json={"app_secret": secret})

    assert attempts == 1
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
