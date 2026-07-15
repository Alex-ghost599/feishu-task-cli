class FeishuTaskError(Exception):
    """Base exception for stable feishu-task failures."""


class ArtifactIntegrityError(FeishuTaskError, ValueError):
    """Raised when an artifact cannot be safely canonicalized or verified."""


class PolicyRejectedError(FeishuTaskError, ValueError):
    """Raised when declared review evidence does not satisfy execution policy."""
