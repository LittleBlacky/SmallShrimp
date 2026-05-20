from __future__ import annotations
from rich.console import Console
import typer
from pathlib import Path


def _resolve_workspace() -> Path:
    """Resolve workspace directory relative to project root, not CWD."""
    # Walk up from this file: src/SmallShrimp/cli/main.py → project root
    pkg_dir = Path(__file__).resolve().parent.parent.parent.parent
    ws = pkg_dir / "workspace"
    if ws.exists():
        return ws
    # Fallback: try CWD
    cwd_ws = Path.cwd() / "workspace"
    if cwd_ws.exists():
        return cwd_ws
    # Last resort
    return Path("workspace")


app = typer.Typer(help="SmallShrimp - AI Agent")


@app.command()
def chat(
    agent_id: str | None = typer.Option(None, "--agent", "-a", help="Agent ID to use"),
    workspace: Path = typer.Option(None, "--workspace", "-w", help="工作区路径"),
) -> None:
    """启动交互式聊天会话。"""
    from .chat import run_chat
    from ..utils.config import Config

    ws = workspace or _resolve_workspace()
    config = Config.from_yaml(ws / "config.user.yaml")
    config.workspace = ws
    run_chat(config, agent_id=agent_id)


@app.command()
def server(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="监听地址"),
    port: int = typer.Option(8000, "--port", "-p", help="监听端口"),
    workspace: Path = typer.Option(Path("workspace"), "--workspace", "-w", help="工作区路径"),
) -> None:
    """启动 WebSocket 服务器。"""
    import asyncio
    from ..server.context import Context
    from ..server.server import Server

    console = Console()
    console.print(f"[cyan]启动 SmallShrimp 服务器...[/cyan]")

    context = Context.from_workspace(workspace)

    server = Server(context)

    async def run():
        api_task = asyncio.create_task(server.start_api(host=host, port=port))
        await server.run()

    asyncio.run(run())


@app.command()
def version() -> None:
    """显示版本号。"""
    from SmallShrimp.__about__ import __version__
    typer.echo(f"SmallShrimp v{__version__}")


if __name__ == "__main__":
    app()