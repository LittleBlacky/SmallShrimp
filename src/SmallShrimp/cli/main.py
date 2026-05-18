from rich.console import Console
import typer
from pathlib import Path

app = typer.Typer(help="SmallShrimp - AI Agent")


@app.command()
def chat(
    agent_id: str | None = typer.Option(None, "--agent", "-a", help="Agent ID to use")
) -> None:
    from .chat import run_chat
    from ..utils.config import Config

    config = Config.from_yaml(Path("workspace/config.user.yaml"))
    config.workspace = Path("workspace")
    run_chat(config, agent_id=agent_id)


@app.command()
def version() -> None:
    """显示版本号。"""
    from SmallShrimp.__about__ import __version__
    typer.echo(f"SmallShrimp v{__version__}")


if __name__ == "__main__":
    app()