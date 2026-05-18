from __future__ import annotations
"""Chat CLI - 基于事件驱动架构的交互式会话。"""
import asyncio
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from ..core.agent import Agent
from ..core.events import OutboundEvent, InboundEvent, CliEventSource
from ..core.eventbus import EventBus
from ..core.agent_loader import AgentLoader
from ..utils.config import Config


class ChatLoop:
    """基于事件驱动的交互式聊天会话。"""

    def __init__(self, config: Config, agent_id: str | None = None):
        self.config = config
        self.console = Console()

        # 创建组件
        self.eventbus = EventBus()
        self.agent_loader = AgentLoader(Path("workspace/agents"))

        # 响应队列
        self.response_queue: asyncio.Queue[OutboundEvent] = asyncio.Queue()

        # 订阅 OutboundEvent
        self.eventbus.subscribe(OutboundEvent, self.handle_outbound_event)

        # 加载 Agent
        agent_id = agent_id or config.default_agent
        self.agent_def = self.agent_loader.load(agent_id)

    async def handle_outbound_event(self, event: OutboundEvent) -> None:
        """处理出站事件，将响应放入队列。"""
        await self.response_queue.put(event)
        self.eventbus.ack(event)

    def get_user_input(self) -> str:
        """获取用户输入。"""
        prompt_text = Text("You", style="cyan")
        user_input = Prompt.ask(prompt_text, console=self.console)
        return user_input.strip()

    def display_agent_response(self, content: str) -> None:
        """显示 Agent 响应。"""
        prefix = Text(f"{self.agent_def.id}: ", style="green")
        self.console.print(prefix, end="")
        self.console.print(content)

    async def run(self) -> None:
        """运行交互式聊天循环。"""
        self.console.print(
            Panel(
                Text("Welcome to SmallShrimp!", style="bold cyan"),
                title="Chat",
                border_style="cyan",
            )
        )
        self.console.print("Type '/help' for commands, 'quit' or 'exit' to end.\n")

        # 启动 EventBus Worker
        self.eventbus.start()

        # 创建 CLI 会话
        agent = Agent(
            self.agent_def,
            self.config,
            None,  # CLI 不需要 tool_registry
            None,  # CLI 不需要 history_manager
        )
        session = agent.new_session(CliEventSource())
        session_id = session.session_id

        try:
            while True:
                user_input = await asyncio.to_thread(self.get_user_input)
                if user_input.lower() in ("quit", "exit", "q"):
                    self.console.print("\n[bold yellow]Goodbye![/bold yellow]")
                    break

                if not user_input:
                    continue

                # 发布 InboundEvent
                event = InboundEvent(
                    session_id=session_id,
                    source=CliEventSource(),
                    content=user_input,
                )
                await self.eventbus.publish(event)

                # 等待响应
                try:
                    response = await asyncio.wait_for(
                        self.response_queue.get(), timeout=60.0
                    )
                    self.display_agent_response(response.content)
                except asyncio.TimeoutError:
                    self.console.print("[red]Agent response timed out[/red]")
                    self.console.print()

        except (KeyboardInterrupt, EOFError):
            self.console.print("\n[bold yellow]Goodbye![/bold yellow]")
        finally:
            await self.eventbus.stop()


def run_chat(config: Config, agent_id: str | None = None) -> None:
    """启动聊天会话。"""
    chat_loop = ChatLoop(config, agent_id=agent_id)
    asyncio.run(chat_loop.run())