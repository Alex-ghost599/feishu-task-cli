from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO
from urllib.parse import urlsplit

import yaml
from pydantic import SecretStr

DEFAULT_API_ORIGIN = "https://open.feishu.cn"


class ConfigError(ValueError):
    """Stable invalid-configuration error with no source content."""


class UnsafeConfigError(ConfigError):
    """Raised before reading a config file that is not private to this user."""


def _try_open(path: Path, flags: int) -> int | None:
    descriptor: int | None = None
    with suppress(OSError):
        descriptor = os.open(path, flags)
    return descriptor


def _try_fstat(descriptor: int) -> os.stat_result | None:
    metadata: os.stat_result | None = None
    with suppress(OSError):
        metadata = os.fstat(descriptor)
    return metadata


def _try_fdopen(descriptor: int) -> TextIO | None:
    handle: TextIO | None = None
    with suppress(OSError):
        handle = os.fdopen(descriptor, encoding="utf-8")
    return handle


def _try_load_and_close(handle: TextIO) -> tuple[object, bool]:
    loaded: object = None
    failed = False
    try:
        with handle:
            loaded = yaml.safe_load(handle) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        failed = True
    return loaded, failed


def _try_close(descriptor: int) -> bool:
    failed = False
    try:
        os.close(descriptor)
    except OSError:
        failed = True
    return not failed


def _read_private_config(path: Path) -> dict[str, object]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = _try_open(path, flags)
    if descriptor is None:
        raise UnsafeConfigError("secret config must be a current-user regular file")
    metadata = _try_fstat(descriptor)
    if metadata is None:
        _try_close(descriptor)
        raise UnsafeConfigError("secret config safety could not be verified")
    if not stat.S_ISREG(metadata.st_mode):
        _try_close(descriptor)
        raise UnsafeConfigError("secret config must be a regular file")
    if metadata.st_uid != os.getuid():
        _try_close(descriptor)
        raise UnsafeConfigError("secret config must be owned by the current user")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        _try_close(descriptor)
        raise UnsafeConfigError("secret config must have exact mode 0600")
    handle = _try_fdopen(descriptor)
    if handle is None:
        _try_close(descriptor)
        raise ConfigError("secret config could not be read or parsed")
    loaded, load_failed = _try_load_and_close(handle)
    if load_failed:
        raise ConfigError("secret config could not be read or parsed")
    if not isinstance(loaded, dict) or not all(isinstance(key, str) for key in loaded):
        raise ConfigError("secret config must contain a string-keyed mapping")
    return loaded


def _optional_text(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty string")
    return value.strip()


def _origin(value: object) -> str:
    message = "FEISHU_API_ORIGIN must be the official Feishu API origin"
    if not isinstance(value, str):
        raise ConfigError(message)
    parse_failed = False
    parsed = None
    hostname = None
    port = None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        parse_failed = True
    if parse_failed or parsed is None:
        raise ConfigError(message)
    if (
        parsed.scheme != "https"
        or hostname != "open.feishu.cn"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != ""
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigError(message)
    if port is not None:
        raise ConfigError(message)
    return DEFAULT_API_ORIGIN


def validate_api_origin(value: object) -> str:
    """Return the one origin to which this Feishu-only project may send credentials."""
    return _origin(value)


@dataclass(frozen=True)
class Settings:
    """Authentication settings with secret values represented by redacting wrappers."""

    api_origin: str = DEFAULT_API_ORIGIN
    app_id: str | None = None
    tenant_id: str | None = None
    account_id: str | None = None
    app_secret: SecretStr | None = None
    user_access_token: SecretStr | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "api_origin", _origin(self.api_origin))
        for field_name in ("app_id", "tenant_id", "account_id"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _optional_text(value, field=field_name),
                )
        for field_name in ("app_secret", "user_access_token"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, SecretStr):
                raise ConfigError(f"{field_name} must use a secret wrapper")

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
            app_secret=SecretStr(app_secret) if app_secret is not None else None,
            user_access_token=(
                SecretStr(user_access_token) if user_access_token is not None else None
            ),
        )
