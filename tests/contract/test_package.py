from typer.testing import CliRunner

from feishu_task_cli import __version__
from feishu_task_cli.cli import app


def test_public_version_is_v0_1_2() -> None:
    assert __version__ == "0.1.2"


def test_cli_help_labels_agent_native_release() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Agent-native Feishu Task CLI" in result.stdout
    assert "review-gated writes" in result.stdout
