from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from feishu_task_cli.auth.config import ConfigError, Settings, UnsafeConfigError
from feishu_task_cli.cli import app


def _assert_no_exception_chain(error: BaseException) -> None:
    assert error.__cause__ is None
    assert error.__context__ is None


def _secret(label: str) -> str:
    return f"synthetic-{label}-" + "x" * 24


def test_cli_has_no_secret_options() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--app-secret" not in result.stdout
    assert "--access-token" not in result.stdout


def test_world_readable_secret_config_is_rejected_without_leaking_secret(
    tmp_path: Path,
) -> None:
    secret = _secret("config")
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({"app_id": "cli_synthetic", "app_secret": secret}))
    path.chmod(0o644)

    with pytest.raises(UnsafeConfigError) as caught:
        Settings.load(config_path=path, environ={})

    assert "0600" in str(caught.value)
    assert secret not in repr(caught.value)
    assert secret not in str(caught.value)


def test_secure_config_and_environment_secrets_are_redacted(tmp_path: Path) -> None:
    app_secret = _secret("app")
    user_token = _secret("user")
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({"app_id": "cli_synthetic", "app_secret": app_secret}))
    path.chmod(0o600)

    settings = Settings.load(
        config_path=path,
        environ={"FEISHU_USER_ACCESS_TOKEN": user_token},
    )

    assert settings.app_id == "cli_synthetic"
    assert settings.app_secret is not None
    assert settings.app_secret.get_secret_value() == app_secret
    assert settings.user_access_token is not None
    assert settings.user_access_token.get_secret_value() == user_token
    assert app_secret not in repr(settings)
    assert user_token not in repr(settings)


def test_invalid_environment_value_does_not_appear_in_validation_error() -> None:
    secret = _secret("invalid-origin")

    with pytest.raises(ConfigError) as caught:
        Settings.load(environ={"FEISHU_API_ORIGIN": secret})

    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
    _assert_no_exception_chain(caught.value)


def test_oauth_redirect_uri_loads_from_explicit_environment_and_config(tmp_path: Path) -> None:
    path = tmp_path / "auth.yaml"
    path.write_text("oauth_redirect_uri: http://127.0.0.1:18765/callback\n")
    path.chmod(0o600)

    configured = Settings.load(config_path=path, environ={})
    overridden = Settings.load(
        config_path=path,
        environ={"FEISHU_OAUTH_REDIRECT_URI": "http://[::1]:18766/callback"},
    )

    assert configured.oauth_redirect_uri == "http://127.0.0.1:18765/callback"
    assert overridden.oauth_redirect_uri == "http://[::1]:18766/callback"


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://127.0.0.1:18765/callback",
        "http://localhost:18765/callback",
        "http://127.0.0.2:18765/callback",
        "http://127.0.0.1/callback",
        "http://127.0.0.1:0/callback",
        "http://127.0.0.1:18765/other",
        "http://user@127.0.0.1:18765/callback",
        "http://127.0.0.1:18765/callback?code=synthetic",
        "http://127.0.0.1:18765/callback#fragment",
        "http://[::1]/callback",
        "http://[::2]:18765/callback",
        "http://[::1]:99999/callback",
    ],
)
def test_oauth_redirect_uri_rejects_noncanonical_or_unsafe_values(redirect_uri: str) -> None:
    with pytest.raises(ConfigError, match="FEISHU_OAUTH_REDIRECT_URI") as caught:
        Settings(oauth_redirect_uri=redirect_uri)

    _assert_no_exception_chain(caught.value)


def test_secret_config_must_be_a_regular_file(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}")
    target.chmod(0o600)
    link = tmp_path / "auth.json"
    os.symlink(target, link)

    with pytest.raises(UnsafeConfigError, match="regular file") as caught:
        Settings.load(config_path=link, environ={})
    _assert_no_exception_chain(caught.value)


def test_malformed_private_config_does_not_leak_its_content(tmp_path: Path) -> None:
    secret = _secret("malformed")
    path = tmp_path / "auth.yaml"
    path.write_text(f"app_secret: [{secret}")
    path.chmod(0o600)

    with pytest.raises(ConfigError) as caught:
        Settings.load(config_path=path, environ={})

    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
    _assert_no_exception_chain(caught.value)


@pytest.mark.parametrize(
    "origin",
    [
        "http://open.feishu.cn",
        "https://evil.example",
        "https://user@open.feishu.cn",
        "https://open.feishu.cn/path",
        "https://open.feishu.cn/",
        "https://open.feishu.cn?query=1",
        "https://open.feishu.cn#fragment",
        "https://open.feishu.cn:443",
        "https://[",
    ],
)
def test_settings_constructor_rejects_noncanonical_feishu_origin(origin: str) -> None:
    with pytest.raises(ConfigError, match="official Feishu API origin") as caught:
        Settings(api_origin=origin, app_id="cli_synthetic")
    _assert_no_exception_chain(caught.value)


def test_config_decode_and_field_type_fail_with_typed_safe_error(tmp_path: Path) -> None:
    path = tmp_path / "auth.yaml"
    path.write_bytes(b"app_id: \xff\xfe\n")
    path.chmod(0o600)

    with pytest.raises(ConfigError) as decode_error:
        Settings.load(config_path=path, environ={})
    with pytest.raises(ConfigError) as type_error:
        Settings.load(environ={"FEISHU_APP_ID": 123})  # type: ignore[dict-item]

    assert "\\xff" not in repr(decode_error.value)
    assert "123" not in repr(type_error.value)
    _assert_no_exception_chain(decode_error.value)


def test_config_read_error_does_not_retain_sensitive_cause(tmp_path: Path) -> None:
    path = tmp_path / _secret("missing-file")

    with pytest.raises(ConfigError) as caught:
        Settings.load(config_path=path, environ={})

    _assert_no_exception_chain(caught.value)
    assert path.name not in repr(caught.value)


def test_fstat_failure_is_typed_and_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "auth.yaml"
    path.write_text("{}")
    path.chmod(0o600)
    secret = _secret("fstat-error")

    def fail_fstat(descriptor: int) -> os.stat_result:
        raise OSError(secret)

    monkeypatch.setattr(os, "fstat", fail_fstat)
    with pytest.raises(ConfigError) as caught:
        Settings.load(config_path=path, environ={})
    _assert_no_exception_chain(caught.value)
    assert secret not in repr(caught.value)


def test_fdopen_failure_is_typed_and_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "auth.yaml"
    path.write_text("{}")
    path.chmod(0o600)
    secret = _secret("fdopen-error")

    def fail_fdopen(descriptor: int, *, encoding: str) -> object:
        raise OSError(secret)

    monkeypatch.setattr(os, "fdopen", fail_fdopen)
    with pytest.raises(ConfigError) as caught:
        Settings.load(config_path=path, environ={})
    _assert_no_exception_chain(caught.value)
    assert secret not in repr(caught.value)


def test_handle_close_failure_is_typed_and_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "auth.yaml"
    path.write_text("{}")
    path.chmod(0o600)
    secret = _secret("handle-close-error")
    original_close = os.close

    class CloseFailHandle:
        def __init__(self, descriptor: int) -> None:
            self.descriptor = descriptor

        def __enter__(self) -> CloseFailHandle:
            return self

        def read(self, size: int = -1) -> str:
            return "{}"

        def __exit__(self, *args: object) -> None:
            original_close(self.descriptor)
            raise OSError(secret)

    def close_fail_fdopen(descriptor: int, *, encoding: str) -> CloseFailHandle:
        return CloseFailHandle(descriptor)

    monkeypatch.setattr(os, "fdopen", close_fail_fdopen)
    with pytest.raises(ConfigError) as caught:
        Settings.load(config_path=path, environ={})
    _assert_no_exception_chain(caught.value)
    assert secret not in repr(caught.value)


def test_final_close_error_does_not_override_primary_safe_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary_secret = _secret("primary-error")
    close_secret = _secret("close-error")
    monkeypatch.setattr(os, "open", lambda *args: 999)

    def fail_fstat(descriptor: int) -> os.stat_result:
        raise OSError(primary_secret)

    def fail_close(descriptor: int) -> None:
        raise OSError(close_secret)

    monkeypatch.setattr(os, "fstat", fail_fstat)
    monkeypatch.setattr(os, "close", fail_close)
    with pytest.raises(ConfigError) as caught:
        Settings.load(config_path="synthetic", environ={})
    _assert_no_exception_chain(caught.value)
    assert primary_secret not in repr(caught.value)
    assert close_secret not in repr(caught.value)


def test_handle_read_failure_has_no_exception_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "auth.yaml"
    path.write_text("{}")
    path.chmod(0o600)
    secret = _secret("handle-read-error")
    original_close = os.close

    class ReadFailHandle:
        def __init__(self, descriptor: int) -> None:
            self.descriptor = descriptor

        def __enter__(self) -> ReadFailHandle:
            return self

        def read(self, size: int = -1) -> str:
            raise OSError(secret)

        def __exit__(self, *args: object) -> None:
            original_close(self.descriptor)

    def read_fail_fdopen(descriptor: int, *, encoding: str) -> ReadFailHandle:
        return ReadFailHandle(descriptor)

    monkeypatch.setattr(os, "fdopen", read_fail_fdopen)
    with pytest.raises(ConfigError) as caught:
        Settings.load(config_path=path, environ={})
    _assert_no_exception_chain(caught.value)
    assert secret not in repr(caught.value)
