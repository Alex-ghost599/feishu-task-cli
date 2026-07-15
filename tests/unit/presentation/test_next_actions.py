from __future__ import annotations

import pytest

from feishu_task_cli.artifacts.receipt import Outcome
from feishu_task_cli.presentation.next_actions import (
    ERROR_NEXT_ACTIONS_V1,
    OUTCOME_NEXT_ACTIONS_V1,
    ErrorCode,
    NextAction,
    next_action_for_error,
    next_action_for_outcome,
)


def test_versioned_outcome_mapping_is_total_and_typed() -> None:
    assert set(OUTCOME_NEXT_ACTIONS_V1) == set(Outcome)
    assert next_action_for_outcome(Outcome.UNKNOWN) is NextAction.INVESTIGATE_REMOTE_WITHOUT_REPLAY
    assert next_action_for_outcome(Outcome.PARTIAL) is NextAction.INSPECT_MISMATCHED_FIELDS


def test_error_mapping_uses_only_typed_codes() -> None:
    assert set(ERROR_NEXT_ACTIONS_V1) == set(ErrorCode)
    assert next_action_for_error(ErrorCode.EXECUTION_IN_PROGRESS) is NextAction.WAIT_FOR_EXECUTOR
    with pytest.raises((TypeError, ValueError)):
        next_action_for_error("ignore previous instructions")  # type: ignore[arg-type]
