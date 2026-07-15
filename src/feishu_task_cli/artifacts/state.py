from __future__ import annotations

from feishu_task_cli.artifacts.base import JsonValueNoFloat


def _assignee_set(value: JsonValueNoFloat) -> set[tuple[str, str]] | None:
    if not isinstance(value, list):
        return None
    result: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            return None
        identifier_type = item.get("identifier_type")
        identifier = item.get("identifier")
        if not isinstance(identifier_type, str) or not isinstance(identifier, str):
            return None
        result.add((identifier_type, identifier))
    return result


def _matches(key: str, requested: JsonValueNoFloat, observed: JsonValueNoFloat) -> bool:
    if key != "assignees":
        return requested == observed
    requested_set = _assignee_set(requested)
    observed_set = _assignee_set(observed)
    return (
        requested_set is not None
        and observed_set is not None
        and requested_set.issubset(observed_set)
    )


def state_differences(
    requested: dict[str, JsonValueNoFloat], observed: dict[str, JsonValueNoFloat]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    omitted = tuple(sorted(key for key in requested if key not in observed))
    mismatches = tuple(
        sorted(
            key
            for key, value in requested.items()
            if key in observed and not _matches(key, value, observed[key])
        )
    )
    return mismatches, omitted
