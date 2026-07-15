from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Callable, Mapping
from typing import TypeAlias, cast

import httpx

from feishu_task_cli.auth.config import validate_api_origin
from feishu_task_cli.errors import FeishuTaskError

LOGGER = logging.getLogger(__name__)
REDACTED = "[REDACTED]"
RETRYABLE_GET_STATUSES = frozenset({429, 502, 503, 504})
MAX_RETRY_DELAY_SECONDS = 60.0
SECRET_KEYS = frozenset(
    {
        "access_token",
        "app_secret",
        "authorization",
        "client_secret",
        "cookie",
        "refresh_token",
        "set-cookie",
        "user_access_token",
    }
)
BEARER_PATTERN = re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]{8,}")
ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(access_token|app_secret|authorization|client_secret|refresh_token|"
    r"user_access_token)\b(\s*[:=]\s*)[\"']?[^\s,}\"']+"
)
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

JsonLike: TypeAlias = None | bool | int | float | str | list["JsonLike"] | dict[str, "JsonLike"]


def _redact_text(value: str, secrets: tuple[str, ...] = ()) -> str:
    result = value
    for secret in secrets:
        if secret:
            result = result.replace(secret, REDACTED)
    result = BEARER_PATTERN.sub(r"\1 [REDACTED]", result)
    return ASSIGNMENT_PATTERN.sub(r"\1\2[REDACTED]", result)


def redact(value: object, *, secrets: tuple[str, ...] = ()) -> object:
    """Recursively copy a value while removing credential-shaped content."""
    if isinstance(value, Mapping):
        return {
            str(key): (
                REDACTED if str(key).lower() in SECRET_KEYS else redact(item, secrets=secrets)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, secrets=secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item, secrets=secrets) for item in value)
    if isinstance(value, str):
        return _redact_text(value, secrets)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_text(str(value), secrets)


def _string_values(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return {item for nested in value.values() for item in _string_values(nested)}
    if isinstance(value, (list, tuple)):
        return {item for nested in value for item in _string_values(nested)}
    if isinstance(value, str):
        return {value}
    return set()


class FeishuTransportError(FeishuTaskError):
    """A transport failure with no embedded request, response, or credential data."""

    def __init__(self, *, method: str, retryable: bool) -> None:
        self.method = method
        self.retryable = retryable
        super().__init__(f"Feishu {method} transport failed")


class FeishuAPIError(FeishuTaskError):
    """A structured, safe projection of a failed Feishu API response."""

    def __init__(
        self,
        *,
        status_code: int,
        api_code: int | str | None,
        request_id: str | None,
        retryable: bool,
    ) -> None:
        self.status_code = status_code
        self.api_code = api_code
        self.request_id = request_id
        self.retryable = retryable
        details = f"Feishu API request failed with HTTP {status_code}"
        if api_code is not None:
            details += f" (code {api_code})"
        if request_id is not None:
            details += f" [request_id={request_id}]"
        super().__init__(details)


def _api_code(value: object) -> int | str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", value):
        return value
    return None


class FeishuClient:
    """Redacted synchronous HTTP transport with method-aware retry boundaries."""

    def __init__(
        self,
        *,
        api_origin: str,
        access_token: str,
        http_client: httpx.Client | None = None,
        max_get_attempts: int = 3,
        debug_hook: Callable[[object], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        backoff_base: float = 0.25,
        backoff_cap: float = 2.0,
        retry_after_cap: float = 30.0,
    ) -> None:
        if not access_token:
            raise ValueError("access token must be non-empty")
        if max_get_attempts < 1 or max_get_attempts > 5:
            raise ValueError("max_get_attempts must be between 1 and 5")
        retry_delays = (backoff_base, backoff_cap, retry_after_cap)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
            or value > MAX_RETRY_DELAY_SECONDS
            for value in retry_delays
        ):
            raise ValueError("retry delays must be finite and between 0 and 60 seconds")
        self.api_origin = validate_api_origin(api_origin)
        self._access_token = access_token
        self._http = http_client or httpx.Client(timeout=10)
        self._max_get_attempts = max_get_attempts
        self._debug_hook = debug_hook
        self._sleep = sleep
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._retry_after_cap = retry_after_cap

    def __repr__(self) -> str:
        return f"FeishuClient(api_origin={self.api_origin!r}, access_token={REDACTED!r})"

    def _emit(self, event: Mapping[str, object]) -> None:
        safe = cast(dict[str, object], redact(event, secrets=(self._access_token,)))
        LOGGER.debug("Feishu HTTP event payload: %s", REDACTED)
        if self._debug_hook is not None:
            self._debug_hook(safe)

    def _request_id(self, response: httpx.Response, *, forbidden: set[str]) -> str | None:
        header_candidates: list[object] = [
            response.headers.get("x-request-id"),
            response.headers.get("x-tt-logid"),
        ]
        for candidate in header_candidates:
            if (
                isinstance(candidate, str)
                and SAFE_REQUEST_ID.fullmatch(candidate)
                and all(not secret or secret not in candidate for secret in forbidden)
            ):
                return candidate
        return None

    def _retry_delay(self, attempt: int, response: httpx.Response | None = None) -> float:
        delay: float = min(self._backoff_cap, self._backoff_base * (2**attempt))
        if response is not None and response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            if retry_after is not None:
                try:
                    parsed = float(retry_after)
                except ValueError:
                    pass
                else:
                    if parsed >= 0:
                        delay = min(parsed, self._retry_after_cap)
        return delay

    def _payload(self, response: httpx.Response) -> object:
        try:
            return response.json()
        except ValueError:
            return response.text

    def request(
        self,
        method: str,
        path: str,
        *,
        json: object | None = None,
        params: Mapping[str, str | int | float | bool | None] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        """Send one request, retrying only bounded idempotent GET operations."""
        normalized = method.upper()
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("path must be an origin-relative absolute path")
        if headers:
            raise ValueError("custom headers are not allowed")
        attempts = self._max_get_attempts if normalized == "GET" else 1
        request_headers = {"Authorization": f"Bearer {self._access_token}"}

        response: httpx.Response | None = None
        for attempt in range(attempts):
            self._emit(
                {
                    "phase": "request",
                    "method": normalized,
                    "attempt": attempt + 1,
                }
            )
            try:
                response = self._http.request(
                    normalized,
                    f"{self.api_origin}{path}",
                    json=json,
                    params=params,
                    headers=request_headers,
                )
            except httpx.TransportError:
                if normalized == "GET" and attempt + 1 < attempts:
                    self._sleep(self._retry_delay(attempt))
                    continue
                raise FeishuTransportError(
                    method=normalized, retryable=normalized == "GET"
                ) from None
            if (
                normalized == "GET"
                and response.status_code in RETRYABLE_GET_STATUSES
                and attempt + 1 < attempts
            ):
                self._sleep(self._retry_delay(attempt, response))
                continue
            break

        assert response is not None
        payload = self._payload(response)
        safe_payload = redact(payload, secrets=(self._access_token,))
        forbidden = {self._access_token}
        forbidden.update(_string_values(json))
        forbidden.update(_string_values(params))
        request_id = self._request_id(response, forbidden=forbidden)
        self._emit(
            {
                "phase": "response",
                "method": normalized,
                "status_code": response.status_code,
                "request_id": request_id,
            }
        )

        code: object = payload.get("code") if isinstance(payload, Mapping) else None
        failed_code = code not in (None, 0, "0")
        if response.status_code >= 400 or failed_code:
            raise FeishuAPIError(
                status_code=response.status_code,
                api_code=_api_code(code),
                request_id=request_id,
                retryable=normalized == "GET" and response.status_code in RETRYABLE_GET_STATUSES,
            )
        if isinstance(safe_payload, Mapping) and "data" in safe_payload:
            return safe_payload["data"]
        return safe_payload
