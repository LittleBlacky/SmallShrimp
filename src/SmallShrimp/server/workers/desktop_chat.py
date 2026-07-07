from __future__ import annotations
"""桌面端 WebSocket 聊天协议处理。"""
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket
from fastapi.websockets import WebSocketDisconnect

from ...core.events.events import WebSocketEventSource, InboundEvent, OutboundEvent

if TYPE_CHECKING:
    from ..context import Context

logger = logging.getLogger(__name__)


class ConnectionState:
    """单个 WebSocket 连接的状态。"""

    def __init__(self, ws: WebSocket, agent: str, session_id: str | None):
        self.ws = ws
        self.agent = agent
        self.session_id = session_id
        self.source = WebSocketEventSource(user_id=f"desktop-{id(self)}")
        self._closed = False

    @property
    def is_closed(self) -> bool:
        return self._closed

    def mark_closed(self) -> None:
        self._closed = True

    async def send_json(self, data: dict[str, Any]) -> None:
        """发送 JSON 消息到客户端。"""
        try:
            await self.ws.send_json(data)
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            self._closed = True


class DesktopChatHandler:
    """桌面端聊天 WebSocket 协议处理器。

    连接参数:
      - agent: Agent 名称（必需）
      - session_id: 会话 ID（可选，不传则创建新会话）

    客户端 → 服务端:
      {"type": "user_message", "content": "...", "attachments": [...]}

    服务端 → 客户端:
      {"type": "session_created", "session_id": "abc"}
      {"type": "text_delta", "content": "你好"}     (P1 流式)
      {"type": "text_done", "content": "完整回复"}
      {"type": "tool_call", "tool": "read_file", "args": {...}}  (P1)
      {"type": "tool_result", "tool": "read_file", "result": "..."}  (P1)
      {"type": "error", "code": "...", "message": "..."}
    """

    def __init__(self, context: Context):
        self.context = context
        # session_id → ConnectionState
        self._connections: dict[str, ConnectionState] = {}

    async def handle_connection(
        self,
        ws: WebSocket,
        agent: str,
        session_id: str | None,
    ) -> None:
        """处理桌面端 WebSocket 连接生命周期。"""
        await ws.accept()

        state = ConnectionState(ws, agent, session_id)

        # 会话管理
        if not session_id:
            session_id = self._create_session(state)
        else:
            # 验证会话存在
            info = self.context.history_manager.get_session_info(session_id)
            if not info:
                await state.send_json({
                    "type": "error",
                    "code": "SESSION_NOT_FOUND",
                    "message": f"会话 {session_id} 不存在",
                })
                await ws.close()
                return

        state.session_id = session_id
        self._connections[session_id] = state

        try:
            await self._run_client_loop(state)
        except WebSocketDisconnect:
            logger.info(f"客户端断开: session={session_id}")
        finally:
            self._connections.pop(session_id, None)

    def _create_session(self, state: ConnectionState) -> str:
        """创建新会话并通知客户端。"""
        import json as _json
        from pathlib import Path

        session_id = uuid.uuid4().hex[:12]
        now = time.time()

        # 写入 meta
        meta_path = Path("workspace/sessions/.meta.json")
        meta_path.parent.mkdir(parents=True, exist_ok=True)

        if meta_path.exists():
            meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        else:
            meta = []

        meta.append({
            "id": session_id,
            "title": "",
            "agent": state.agent,
            "created_at": now,
            "last_active_at": now,
        })
        meta_path.write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        # 创建空消息文件
        session_file = Path(f"workspace/sessions/{session_id}.jsonl")
        session_file.touch()

        logger.info(f"创建新会话: {session_id}, agent={state.agent}")
        return session_id

    async def _run_client_loop(self, state: ConnectionState) -> None:
        """运行客户端消息接收循环。"""
        # 通知客户端会话已就绪
        await state.send_json({
            "type": "session_created",
            "session_id": state.session_id,
        })

        while not state.is_closed:
            try:
                data = await state.ws.receive_json()
                msg_type = data.get("type", "")

                if msg_type == "user_message":
                    await self._handle_user_message(state, data)
                else:
                    await state.send_json({
                        "type": "error",
                        "code": "UNKNOWN_MESSAGE_TYPE",
                        "message": f"未知消息类型: {msg_type}",
                    })

            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                await state.send_json({
                    "type": "error",
                    "code": "INVALID_JSON",
                    "message": "无效的 JSON 格式",
                })
            except Exception as e:
                logger.error(f"客户端循环异常: {e}")
                await state.send_json({
                    "type": "error",
                    "code": "INTERNAL_ERROR",
                    "message": str(e),
                })
                break

    async def _handle_user_message(
        self, state: ConnectionState, data: dict[str, Any]
    ) -> None:
        """处理用户消息。"""
        content = data.get("content", "").strip()
        if not content:
            await state.send_json({
                "type": "error",
                "code": "EMPTY_MESSAGE",
                "message": "消息不能为空",
            })
            return

        # 发布到 EventBus
        event = InboundEvent(
            session_id=state.session_id,
            source=state.source,
            content=content,
            timestamp=time.time(),
        )
        await self.context.eventbus.publish(event)
        logger.debug(f"用户消息已发布: session={state.session_id}")

    async def on_outbound_event(self, event: OutboundEvent) -> None:
        """接收 OutboundEvent，路由到对应连接。"""
        state = self._connections.get(event.session_id)
        if not state or state.is_closed:
            return

        if event.error:
            await state.send_json({
                "type": "error",
                "code": "AGENT_ERROR",
                "message": event.error,
            })
        else:
            await state.send_json({
                "type": "text_done",
                "content": event.content,
            })
