from __future__ import annotations

from collections.abc import Mapping, Sequence

from feishu_task_cli.artifacts.base import JsonValueNoFloat

ALLOWED_TASK_FIELDS = frozenset({"completed_at", "description", "due", "summary"})
ASSIGNEE_IDENTIFIER_TYPES = frozenset({"open_id", "user_id", "union_id"})
MAX_ASSIGNEES = 50
MAX_TASK_TEXT_LENGTH = 3000


def _normalize_timestamp(value: object, *, field_name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{field_name} must be a millisecond timestamp")
    normalized = str(value)
    if not normalized.isascii() or not normalized.isdigit() or len(normalized) > 20:
        raise ValueError(f"{field_name} must be a non-negative millisecond timestamp")
    return normalized


def normalize_task_fields(
    action: str, values: Mapping[str, JsonValueNoFloat]
) -> dict[str, JsonValueNoFloat]:
    fields = dict(values)
    if action == "assign":
        if set(fields) != {"assignees"}:
            raise ValueError("assign requires exactly the assignees requested field")
        return fields

    unsupported = sorted(set(fields).difference(ALLOWED_TASK_FIELDS))
    if unsupported:
        raise ValueError(f"unsupported Task fields: {', '.join(unsupported)}")
    if action == "create" and "summary" not in fields:
        raise ValueError("create requires summary")
    if action == "update" and not fields:
        raise ValueError("update requires at least one Task field")
    if action == "complete" and set(fields) != {"completed_at"}:
        raise ValueError("complete requires exactly completed_at")

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


def normalize_assignee_pairs(
    values: Sequence[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    normalized: list[tuple[str, str]] = []
    for identifier_type, identifier in values:
        if identifier_type not in ASSIGNEE_IDENTIFIER_TYPES:
            raise ValueError("assignee identifier type is unsupported")
        canonical_identifier = identifier.strip()
        if not canonical_identifier:
            raise ValueError("typed assignee identifier must be non-empty")
        if any(character.isspace() for character in canonical_identifier):
            raise ValueError("typed assignee identifier must use canonical non-whitespace form")
        pair = (identifier_type, canonical_identifier)
        if pair not in normalized:
            normalized.append(pair)

    if len({identifier_type for identifier_type, _ in normalized}) > 1:
        raise ValueError("one plan cannot mix assignee identifier types")
    if len(normalized) > MAX_ASSIGNEES:
        raise ValueError("one plan can contain at most 50 unique assignees")
    return tuple(normalized)
