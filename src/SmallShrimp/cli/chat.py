from __future__ import annotations
"""Chat CLI - 基于事件驱动架构的交互式会话。"""
import asyncio
import logging
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from ..core.agent import Agent
from ..core.events import OutboundEvent, InboundEvent, CliEventSource
from ..core.eventbus import EventBus
from ..core.agent_loader import AgentLoader
from ..core.history import HistoryManager
from ..utils.config import Config

logger = logging.getLogger(__name__)


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

        # 创建完备的组件
        history_manager = HistoryManager(Path("workspace/sessions"))
        from ..tools import create_tool_registry
        tool_registry = create_tool_registry(self.config.data)

        # 创建 Agent 实例
        self.agent = Agent(
            self.agent_def,
            self.config,
            tool_registry,
            history_manager,
        )
        self.session = self.agent.new_session(source=CliEventSource())

        # 订阅 InboundEvent - 直接处理消息
        self.eventbus.subscribe(InboundEvent, self.handle_inbound_event)

    async def handle_inbound_event(self, event: InboundEvent) -> None:
        """处理入站事件，调用 Agent 生成响应。"""
        try:
            # 处理斜杠命令
            if event.content.startswith("/"):
                from ..core.commands.registry import CommandRegistry
                from ..core.commands.handlers import CommandContext

                cmd_context = CommandContext(self.session)
                result = await CommandRegistry.dispatch(event.content, cmd_context)
                if result:
                    await self.eventbus.publish(
                        OutboundEvent(
                            session_id=event.session_id,
                            source=event.source,
                            content=result,
                        )
                    )
                else:
                    await self.eventbus.publish(
                        OutboundEvent(
                            session_id=event.session_id,
                            source=event.source,
                            content="未知命令",
                        )
                    )
            else:
                # 普通聊天
                response = await self.session.chat(event.content)
                await self.eventbus.publish(
                    OutboundEvent(
                        session_id=event.session_id,
                        source=event.source,
                        content=response,
                    )
                )
        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            await self.eventbus.publish(
                OutboundEvent(
                    session_id=event.session_id,
                    source=event.source,
                    content="",
                    error=str(e),
                )
            )
        self.eventbus.ack(event)

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
        prefix = Text(f"{self.agent_def.name}: ", style="green")
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

        session_id = self.session.session_id

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
                    if response.error:
                        self.console.print(f"[red]错误: {response.error}[/red]")
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