from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from feishu_task_cli.auth.config import Settings, UnsafeConfigError
from feishu_task_cli.cli import app


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

    with pytest.raises(ValueError) as caught:
        Settings.load(environ={"FEISHU_API_ORIGIN": secret})

    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)


def test_invalid_origin_port_is_not_retained_as_exception_cause() -> None:
    with pytest.raises(ValueError) as caught:
        Settings.load(environ={"FEISHU_API_ORIGIN": "https://example.test:private-value"})

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://127.0.0.1/callback",
        "http://localhost:8765/callback",
        "https://127.0.0.1:8765/callback",
        "http://127.0.0.1:8765/",
        "http://127.0.0.1:8765/callback?unsafe=1",
    ],
)
def test_oauth_redirect_uri_must_be_fixed_exact_loopback(redirect_uri: str) -> None:
    with pytest.raises(ValueError, match="FEISHU_OAUTH_REDIRECT_URI"):
        Settings.load(environ={"FEISHU_OAUTH_REDIRECT_URI": redirect_uri})


def test_oauth_redirect_uri_and_scopes_load_explicitly() -> None:
    settings = Settings.load(
        environ={
            "FEISHU_OAUTH_REDIRECT_URI": "http://127.0.0.1:8765/callback",
            "FEISHU_OAUTH_SCOPES": "task:task:read offline_access task:task:write",
        }
    )

    assert settings.oauth_redirect_uri == "http://127.0.0.1:8765/callback"
    assert settings.oauth_scopes == (
        "offline_access",
        "task:task:read",
        "task:task:write",
    )


def test_secret_config_must_be_a_regular_file(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}")
    target.chmod(0o600)
    link = tmp_path / "auth.json"
    os.symlink(target, link)

    with pytest.raises(UnsafeConfigError, match="regular file"):
        Settings.load(config_path=link, environ={})


def test_malformed_private_config_does_not_leak_its_content(tmp_path: Path) -> None:
    secret = _secret("malformed")
    path = tmp_path / "auth.yaml"
    path.write_text(f"app_secret: [{secret}")
    path.chmod(0o600)

    with pytest.raises(ValueError) as caught:
        Settings.load(config_path=path, environ={})

    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
