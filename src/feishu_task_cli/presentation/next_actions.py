from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final

from feishu_task_cli.artifacts.receipt import Outcome

NEXT_ACTION_MAPPING_VERSION: Final[str] = "v1"


class NextAction(StrEnum):
    NONE = "none"
    INSPECT_MISMATCHED_FIELDS = "inspect_mismatched_fields"
    INVESTIGATE_REMOTE_WITHOUT_REPLAY = "investigate_remote_state_without_replay"
    CREATE_NEW_PLAN_AFTER_FAILURE = "create_new_plan_after_definitive_failure"
    RESOLVE_REVIEW_OR_POLICY = "resolve_review_or_policy_rejection"
    WAIT_FOR_EXECUTOR = "wait_for_active_executor"
    REAUTHENTICATE = "reauthenticate_explicit_context"
    FIX_INPUT = "fix_invalid_input"
    VERIFY_ARTIFACT = "verify_artifact_integrity_and_version"
    INSPECT_REMOTE = "inspect_remote_error_without_automatic_replay"


class ErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    CONFIGURATION_FAILED = "configuration_failed"
    AUTHENTICATION_FAILED = "authentication_failed"
    POLICY_REJECTED = "policy_rejected"
    API_FAILED = "api_failed"
    EXECUTION_UNKNOWN = "execution_unknown"
    EXECUTION_PARTIAL = "execution_partial"
    ARTIFACT_INTEGRITY_FAILED = "artifact_integrity_failed"
    EXECUTION_IN_PROGRESS = "execution_in_progress"
    REPLAY_BLOCKED = "replay_blocked"
    OPERATION_FAILED = "operation_failed"


OUTCOME_NEXT_ACTIONS_V1 = MappingProxyType(
    {
        Outcome.VERIFIED: NextAction.NONE,
        Outcome.PARTIAL: NextAction.INSPECT_MISMATCHED_FIELDS,
        Outcome.UNKNOWN: NextAction.INVESTIGATE_REMOTE_WITHOUT_REPLAY,
        Outcome.FAILED: NextAction.CREATE_NEW_PLAN_AFTER_FAILURE,
        Outcome.REJECTED: NextAction.RESOLVE_REVIEW_OR_POLICY,
    }
)

ERROR_NEXT_ACTIONS_V1 = MappingProxyType(
    {
        ErrorCode.INVALID_INPUT: NextAction.FIX_INPUT,
        ErrorCode.CONFIGURATION_FAILED: NextAction.FIX_INPUT,
        ErrorCode.AUTHENTICATION_FAILED: NextAction.REAUTHENTICATE,
        ErrorCode.POLICY_REJECTED: NextAction.RESOLVE_REVIEW_OR_POLICY,
        ErrorCode.API_FAILED: NextAction.INSPECT_REMOTE,
        ErrorCode.EXECUTION_UNKNOWN: NextAction.INVESTIGATE_REMOTE_WITHOUT_REPLAY,
        ErrorCode.EXECUTION_PARTIAL: NextAction.INSPECT_MISMATCHED_FIELDS,
        ErrorCode.ARTIFACT_INTEGRITY_FAILED: NextAction.VERIFY_ARTIFACT,
        ErrorCode.EXECUTION_IN_PROGRESS: NextAction.WAIT_FOR_EXECUTOR,
        ErrorCode.REPLAY_BLOCKED: NextAction.CREATE_NEW_PLAN_AFTER_FAILURE,
        ErrorCode.OPERATION_FAILED: NextAction.INSPECT_REMOTE,
    }
)


def next_action_for_outcome(outcome: Outcome) -> NextAction:
    if not isinstance(outcome, Outcome):
        raise TypeError("outcome must be a typed Outcome")
    return OUTCOME_NEXT_ACTIONS_V1[outcome]


def next_action_for_error(code: ErrorCode) -> NextAction:
    if not isinstance(code, ErrorCode):
        raise TypeError("code must be a typed ErrorCode")
    return ERROR_NEXT_ACTIONS_V1[code]
