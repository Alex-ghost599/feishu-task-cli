from typer.testing import CliRunner

from feishu_task_cli import __version__
from feishu_task_cli.cli import app


def test_initial_version_is_unreleased() -> None:
    assert __version__ == "0.0.0"


def test_cli_help_labels_bootstrap_as_pre_alpha() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Agent-native Feishu Task CLI" in result.stdout
    assert "pre-alpha" in result.stdout
