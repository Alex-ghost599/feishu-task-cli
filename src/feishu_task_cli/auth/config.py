from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import SecretStr

DEFAULT_API_ORIGIN = "https://open.feishu.cn"
DEFAULT_OAUTH_SCOPES = ("offline_access", "task:task:write")


class UnsafeConfigError(ValueError):
    """Raised before reading a config file that is not private to this user."""


def _read_private_config(path: Path) -> dict[str, object]:
    parse_failed = False
    read_failed = False
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    open_failed = False
    try:
        descriptor = os.open(path, flags)
    except OSError:
        open_failed = True
    if open_failed:
        raise UnsafeConfigError("secret config must be a current-user regular file")
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise UnsafeConfigError("secret config must be a regular file")
        if metadata.st_uid != os.getuid():
            raise UnsafeConfigError("secret config must be owned by the current user")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise UnsafeConfigError("secret config must have exact mode 0600")
        with os.fdopen(descriptor, encoding="utf-8") as handle:
            descriptor = -1
            try:
                loaded = yaml.safe_load(handle) or {}
            except yaml.YAMLError:
                parse_failed = True
                loaded = None
    except (OSError, UnicodeError):
        read_failed = True
        loaded = None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if read_failed:
        raise ValueError("secret config could not be read")
    if parse_failed:
        raise ValueError("secret config could not be parsed")
    if not isinstance(loaded, dict) or not all(isinstance(key, str) for key in loaded):
        raise ValueError("secret config must contain a string-keyed mapping")
    return loaded


def _optional_text(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _origin(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("FEISHU_API_ORIGIN must be an HTTPS origin without a path")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("FEISHU_API_ORIGIN must be an HTTPS origin without a path")
    invalid_port = False
    try:
        port = parsed.port
    except ValueError:
        invalid_port = True
        port = None
    if invalid_port:
        raise ValueError("FEISHU_API_ORIGIN must be an HTTPS origin without a path")
    host = parsed.hostname.lower()
    return f"https://{host}{f':{port}' if port is not None else ''}"


def _redirect_uri(value: object) -> str | None:
    text = _optional_text(value, field="oauth_redirect_uri")
    if text is None:
        return None
    parsed = urlsplit(text)
    try:
        port = parsed.port
    except ValueError:
        port = None
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or port == 0
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "FEISHU_OAUTH_REDIRECT_URI must be an exact http://127.0.0.1:<port>/<path> URL"
        )
    return f"http://127.0.0.1:{port}{parsed.path}"


def _scopes(value: object) -> tuple[str, ...]:
    text = _optional_text(value, field="oauth_scopes")
    requested = set(DEFAULT_OAUTH_SCOPES if text is None else text.split())
    requested.add("offline_access")
    if len(requested) > 50 or any(
        not re.fullmatch(r"[A-Za-z0-9._:-]+", scope) for scope in requested
    ):
        raise ValueError("FEISHU_OAUTH_SCOPES must contain at most 50 valid scope names")
    return tuple(sorted(requested))


@dataclass(frozen=True)
class Settings:
    """Authentication settings with secret values represented by redacting wrappers."""

    api_origin: str = DEFAULT_API_ORIGIN
    app_id: str | None = None
    tenant_id: str | None = None
    account_id: str | None = None
    oauth_redirect_uri: str | None = None
    oauth_scopes: tuple[str, ...] = DEFAULT_OAUTH_SCOPES
    app_secret: SecretStr | None = None
    user_access_token: SecretStr | None = None

    @classmethod
    def load(
        cls,
        config_path: str | Path | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> Settings:
        """Load explicit private config, then apply process-environment overrides."""
        source = dict(_read_private_config(Path(config_path))) if config_path is not None else {}
        env = os.environ if environ is None else environ

        def selected(environment_name: str, config_name: str) -> object:
            return env.get(environment_name, source.get(config_name))

        app_secret = _optional_text(selected("FEISHU_APP_SECRET", "app_secret"), field="app_secret")
        user_access_token = _optional_text(
            selected("FEISHU_USER_ACCESS_TOKEN", "user_access_token"),
            field="user_access_token",
        )
        return cls(
            api_origin=_origin(selected("FEISHU_API_ORIGIN", "api_origin") or DEFAULT_API_ORIGIN),
            app_id=_optional_text(selected("FEISHU_APP_ID", "app_id"), field="app_id"),
            tenant_id=_optional_text(selected("FEISHU_TENANT_ID", "tenant_id"), field="tenant_id"),
            account_id=_optional_text(
                selected("FEISHU_ACCOUNT_ID", "account_id"), field="account_id"
            ),
            oauth_redirect_uri=_redirect_uri(
                selected("FEISHU_OAUTH_REDIRECT_URI", "oauth_redirect_uri")
            ),
            oauth_scopes=_scopes(selected("FEISHU_OAUTH_SCOPES", "oauth_scopes")),
            app_secret=SecretStr(app_secret) if app_secret is not None else None,
            user_access_token=(
                SecretStr(user_access_token) if user_access_token is not None else None
            ),
        )
