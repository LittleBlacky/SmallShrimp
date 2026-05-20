from __future__ import annotations
from rich.console import Console
import typer
from pathlib import Path
import os


def _default_workspace() -> Path:
    """Find workspace: env var > ~/.smallshrimp > package dir."""
    env_ws = os.environ.get("SMALLSHRIMP_WORKSPACE")
    if env_ws:
        return Path(env_ws)
    if os.name == "nt":
        home_ws = Path(os.environ.get("APPDATA", "~")) / "SmallShrimp"
    else:
        home_ws = Path.home() / ".smallshrimp"
    if home_ws.exists():
        return home_ws
    pkg_dir = Path(__file__).resolve().parent.parent.parent.parent
    pkg_ws = pkg_dir / "workspace"
    if pkg_ws.exists():
        return pkg_ws
    home_ws.mkdir(parents=True, exist_ok=True)
    return home_ws


def _resolve_workspace() -> Path:
    ws = _default_workspace()
    ws.mkdir(parents=True, exist_ok=True)
    return ws


app = typer.Typer(help="SmallShrimp - AI Agent")


@app.command()
def init(
    path: Path = typer.Option(None, "--path", "-p", help="工作区路径 (默认 ~/.smallshrimp)"),
) -> None:
    """初始化工作区，创建配置文件和目录结构。"""
    ws = path or _default_workspace()
    ws.mkdir(parents=True, exist_ok=True)

    # 创建子目录
    for d in ["agents", "skills", "sessions", "memories", "crons", ".cache"]:
        (ws / d).mkdir(parents=True, exist_ok=True)

    # 创建默认配置
    config_file = ws / "config.user.yaml"
    if not config_file.exists():
        config_file.write_text("""\
# SmallShrimp 用户配置
default_provider: deepseek
default_agent: pickle

providers:
  deepseek:
    api_key: your-api-key-here
    api_base: https://api.deepseek.com

# 权限模式: default | acceptEdits | bypassPermissions | plan | dontAsk
permission_mode: default
""", encoding="utf-8")

    # 创建默认 Agent
    agent_dir = ws / "agents" / "pickle"
    agent_dir.mkdir(parents=True, exist_ok=True)
    agent_file = agent_dir / "AGENT.md"
    if not agent_file.exists():
        agent_file.write_text("""\
---
name: Pickle
description: 默认助手
llm:
  provider: deepseek
  model: deepseek/deepseek-chat
  temperature: 0.7
  context_window: 200000
---

# Pickle

你是一个友好的 AI 助手。用中文回复。
""", encoding="utf-8")

    console = Console()
    console.print(f"\n[green]✓ 工作区已初始化: {ws}[/green]")
    console.print(f"  配置文件: {config_file}")
    console.print(f"  默认 Agent: {agent_dir}")
    console.print(f"\n  [dim]设置 API key 后运行 smallshrimp chat 开始[/dim]\n")


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