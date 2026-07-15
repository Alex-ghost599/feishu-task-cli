"""Secure authentication configuration and token handling."""

from feishu_task_cli.auth.config import ConfigError, Settings, UnsafeConfigError
from feishu_task_cli.auth.context import build_auth_context, resolve_auth_context
from feishu_task_cli.auth.keyring_store import TokenStore, TokenStoreError
from feishu_task_cli.auth.oauth import OAuthClient, OAuthDeniedError, OAuthError

__all__ = [
    "OAuthClient",
    "OAuthDeniedError",
    "OAuthError",
    "ConfigError",
    "Settings",
    "TokenStore",
    "TokenStoreError",
    "UnsafeConfigError",
    "build_auth_context",
    "resolve_auth_context",
]
