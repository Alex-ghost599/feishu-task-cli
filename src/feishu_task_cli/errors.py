class FeishuTaskError(Exception):
    """Base exception for stable feishu-task failures."""


class ArtifactIntegrityError(FeishuTaskError, ValueError):
    """Raised when an artifact cannot be safely canonicalized or verified."""
