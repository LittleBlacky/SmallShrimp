import asyncio
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from ..core.agent import Agent
from ..core.agent_loader import AgentLoader
from ..utils.config import Config
from ..tools.registry import ToolRegistry
from ..core.history import HistoryManager
from ..core.commands.registry import CommandRegistry

console = Console()

async def get_user_input() -> str:
    return await asyncio.to_thread(input, "You: ")

def display_welcome() -> None:
    console.print(
        Panel(
            Text("Welcome to SmallShrimp!", style="bold cyan"),
            title="Chat",
            border_style="cyan",
        )
    )
    console.print("Type 'quit' or 'exit' to end the session.\n")

def display_response(response: str) -> None:
    console.print(f"\nAgent: {response}\n")

async def run_chat_loop() -> None:
    """运行聊天循环。"""
    display_welcome()

    # 加载配置和 Agent（注意路径！）
    config = Config.from_yaml(Path("workspace/config.user.yaml"))
    loader = AgentLoader(Path("workspace/agents"))
    agent_def = loader.load("pickle")

    # 创建工具注册表并注册内置工具    
    tool_registry = ToolRegistry.from_module("SmallShrimp.tools.builtin_tools")
    
    # 历史管理器
    history_manager = HistoryManager(Path("workspace/sessions"))

    agent = Agent(agent_def, config, tool_registry, history_manager)

    # 询问是否恢复旧会话
    sessions = history_manager.list_sessions()
    if sessions:
        console.print(f"[dim]找到 {len(sessions)} 个历史会话[/dim]")
        session_id = sessions[0]["session_id"]  # 默认恢复最新的
        messages = history_manager.load(session_id)
        console.print(f"[dim]恢复会话: {session_id[:8]}...[/dim]\n")
    else:
        session_id = None
        messages = []

    session = agent.new_session(session_id)
    
    if messages:
        for msg in messages:
            session.state.messages.append(msg)

    try:
        while True:
            user_input = await get_user_input()
            if user_input.lower() in ("quit", "exit", "q"):
                console.print("\n[bold yellow]Goodbye![/bold yellow]")
                break

            parsed = CommandRegistry.parse(user_input)
            if parsed:
                name, args = parsed
                cmd = CommandRegistry.get(name)
                if cmd:
                    from ..core.commands.handlers import CommandContext
                    context = CommandContext(session)
                    response = await cmd.handler(context, args)
                    console.print(f"\n{response}\n")
                    continue
                else:
                    console.print(f"\n[red]未知命令: /{name}[/red]\n")
                    continue

            if not user_input.strip():
                continue
            try:
                response = await session.chat(user_input)
                display_response(response)
            except Exception as e:
                console.print(f"\n[bold red]Error:[/bold red] {e}\n")
    except (KeyboardInterrupt, EOFError):
        console.print("\n[bold yellow]Goodbye![/bold yellow]")