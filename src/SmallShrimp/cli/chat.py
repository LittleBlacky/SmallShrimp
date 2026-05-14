import asyncio
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from core.agent import Agent
from core.agent_loader import AgentLoader
from utils.config import Config

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
    agent = Agent(agent_def, config)
    session = agent.new_session()

    try:
        while True:
            user_input = await get_user_input()
            if user_input.lower() in ("quit", "exit", "q"):
                console.print("\n[bold yellow]Goodbye![/bold yellow]")
                break
            if not user_input.strip():
                continue
            try:
                response = await session.chat(user_input)
                display_response(response)
            except Exception as e:
                console.print(f"\n[bold red]Error:[/bold red] {e}\n")
    except (KeyboardInterrupt, EOFError):
        console.print("\n[bold yellow]Goodbye![/bold yellow]")