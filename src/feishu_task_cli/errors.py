class FeishuTaskError(Exception):
    """Base exception for stable feishu-task failures."""


class ArtifactIntegrityError(FeishuTaskError, ValueError):
    """Raised when an artifact cannot be safely canonicalized or verified."""


class PolicyRejectedError(FeishuTaskError, ValueError):
    """Raised when an execution review does not satisfy the selected policy."""


class AuthContextMismatchError(FeishuTaskError):
    """Raised before mutation when the live identity differs from the Plan."""


class PreconditionChangedError(FeishuTaskError):
    """Raised before mutation when the observed Task changed after planning."""


class FeishuResponseError(FeishuTaskError):
    """Raised when a successful HTTP response cannot satisfy the Task contract."""


class ExecutionInProgressError(FeishuTaskError):
    """Raised when another local process holds the Plan execution lock."""


class ReplayBlockedError(FeishuTaskError):
    """Raised when a Plan has already been claimed or completed."""


class UnknownExecutionError(FeishuTaskError):
    """Raised when a mutation outcome cannot be proven and replay is unsafe."""


class JournalCorruptError(FeishuTaskError):
    """Raised when an execution journal record cannot be trusted."""


class JournalPermissionError(FeishuTaskError):
    """Raised when journal storage is accessible by another local user."""
