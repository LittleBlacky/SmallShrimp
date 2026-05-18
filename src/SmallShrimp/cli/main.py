from rich.console import Console
import typer
from pathlib import Path

app = typer.Typer(help="SmallShrimp - AI Agent")


@app.command()
def chat(
    agent_id: str | None = typer.Option(None, "--agent", "-a", help="Agent ID to use")
) -> None:
    """启动交互式聊天会话。"""
    from .chat import run_chat
    from ..utils.config import Config

    config = Config.from_yaml(Path("workspace/config.user.yaml"))
    config.workspace = Path("workspace")
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