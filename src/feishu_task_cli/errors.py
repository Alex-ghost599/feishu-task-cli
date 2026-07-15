class FeishuTaskError(Exception):
    """Base exception for stable feishu-task failures."""


class ArtifactIntegrityError(FeishuTaskError, ValueError):
    """Raised when an artifact cannot be safely canonicalized or verified."""


class PolicyRejectedError(FeishuTaskError, ValueError):
    """Raised when an execution review does not satisfy the selected policy."""
