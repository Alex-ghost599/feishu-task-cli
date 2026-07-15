"""Command-line entry point."""

import typer

app = typer.Typer(
    help="Agent-native Feishu Task CLI (pre-alpha; mutation commands are not implemented)."
)


@app.callback()
def main() -> None:
    """Expose the pre-alpha command group without mutation behavior."""
