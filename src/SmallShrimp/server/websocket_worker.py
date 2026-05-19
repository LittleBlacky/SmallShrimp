from __future__ import annotations
"""WebSocket Worker - 管理 WebSocket 连接并广播事件。"""
import logging
import time
import dataclasses
from typing import TYPE_CHECKING, Set

from pydantic import BaseModel, Field
from fastapi import WebSocket
from fastapi.websockets import WebSocketDisconnect
from pydantic import ValidationError

from .worker import SubscriberWorker
from ..core.events import Event, EventSource, InboundEvent, OutboundEvent

if TYPE_CHECKING:
    from .context import Context

logger = logging.getLogger(__name__)


class WebSocketMessage(BaseModel):
    """客户端发送的 WebSocket 消息。"""
    source: str = Field(..., min_length=1, description="客户端标识符")
    content: str = Field(..., min_length=1, description="消息内容")
    agent_id: str | None = Field(None, description="目标 Agent ID（可选）")


class WebSocketWorker(SubscriberWorker):
    """管理 WebSocket 连接并广播事件。"""

    def __init__(self, context: "Context"):
        super().__init__(context)
        self.clients: Set[WebSocket] = set()

        # 订阅事件类型
        self.context.eventbus.subscribe(InboundEvent, self.handle_event)
        self.context.eventbus.subscribe(OutboundEvent, self.handle_event)
        self.logger.info("WebSocketWorker 已订阅事件类型")

    async def handle_connection(self, ws: WebSocket) -> None:
        """处理单个 WebSocket 连接生命周期。"""
        self.clients.add(ws)
        self.logger.info(f"WebSocket 客户端已连接，当前连接数: {len(self.clients)}")

        try:
            await self._run_client_loop(ws)
        finally:
            self.clients.discard(ws)
            self.logger.info(f"WebSocket 客户端已断开，当前连接数: {len(self.clients)}")

    async def _run_client_loop(self, ws: WebSocket) -> None:
        """运行客户端消息接收循环。"""
        from ..core.events import WebSocketEventSource

        while True:
            try:
                data = await ws.receive_json()
                msg = WebSocketMessage(**data)

                source = WebSocketEventSource(user_id=msg.source)
                session_id = self._get_or_create_session_id(source)

                event = InboundEvent(
                    session_id=session_id,
                    source=source,
                    content=msg.content,
                    timestamp=time.time(),
                )

                await self.context.eventbus.publish(event)
                self.logger.debug(f"从 WebSocket 发布 InboundEvent: {msg.source}")

            except WebSocketDisconnect:
                self.logger.info("客户端正常断开")
                break
            except ValidationError as e:
                await ws.send_json(
                    {"type": "error", "message": f"验证错误: {e}"}
                )
                self.logger.warning(f"客户端验证错误: {e}")
            except Exception as e:
                self.logger.error(f"客户端循环异常: {e}")
                break

    async def handle_event(self, event: Event) -> None:
        """处理 EventBus 事件，广播给 WebSocket 客户端。"""
        if not self.clients:
            return

        # 序列化为字典
        event_dict = {
            "type": event.__class__.__name__,
        }
        event_dict.update(dataclasses.asdict(event))

        # 将 EventSource 转为字符串
        if "source" in event_dict and hasattr(event.source, "__str__"):
            event_dict["source"] = str(event.source)

        self.logger.debug(
            f"广播 {event.__class__.__name__} 给 {len(self.clients)} 个客户端"
        )

        for client in list(self.clients):
            try:
                await client.send_json(event_dict)
            except Exception as e:
                self.logger.error(f"发送消息给客户端失败: {e}")
                self.clients.discard(client)

    def _get_or_create_session_id(self, source: "EventSource") -> str:
        """获取或创建指定来源的会话 ID。"""
        source_str = str(source)

        # 从配置缓存中查找
        if hasattr(self.context, "config") and hasattr(self.context.config, "sources"):
            source_session = self.context.config.sources.get(source_str)
            if source_session:
                return source_session.session_id

        # 首次创建会话
        if hasattr(self.context, "agent_loader"):
            default_agent = "pickle"
            if hasattr(self.context, "config") and hasattr(self.context.config, "default_agent"):
                default_agent = self.context.config.default_agent

            try:
                agent_def = self.context.agent_loader.load(default_agent)
                from ..core.agent import Agent

                agent = Agent(
                    agent_def,
                    self.context.config,
                    getattr(self.context, "tool_registry", None),
                    getattr(self.context, "history_manager", None),
                )
                session = agent.new_session(source)

                # 缓存会话 ID 到配置
                if hasattr(self.context, "config") and hasattr(self.context.config, "set_runtime"):
                    from ..utils.config import SourceSessionConfig
                    self.context.config.set_runtime(
                        f"sources.{source_str}",
                        SourceSessionConfig(session_id=session.session_id),
                    )

                return session.session_id
            except Exception as e:
                self.logger.warning(f"创建会话失败: {e}")

        # 回退：生成临时会话 ID
        import uuid
        return str(uuid.uuid4())[:8]