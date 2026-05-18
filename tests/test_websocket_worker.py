from __future__ import annotations
"""WebSocket Worker 测试。"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import ValidationError

from src.SmallShrimp.core.events import WebSocketEventSource, InboundEvent, OutboundEvent
from src.SmallShrimp.server.websocket_worker import WebSocketWorker, WebSocketMessage


def test_websocket_message_valid():
    """测试有效的 WebSocket 消息。"""
    msg = WebSocketMessage(source="user123", content="Hello")
    assert msg.source == "user123"
    assert msg.content == "Hello"
    assert msg.agent_id is None


def test_websocket_message_with_agent_id():
    """测试带 agent_id 的 WebSocket 消息。"""
    msg = WebSocketMessage(source="user123", content="Hello", agent_id="pickle")
    assert msg.agent_id == "pickle"


def test_websocket_message_validation_source_required():
    """测试 source 是必需字段。"""
    with pytest.raises(ValidationError):
        WebSocketMessage(content="Hello")


def test_websocket_message_validation_content_required():
    """测试 content 是必需字段。"""
    with pytest.raises(ValidationError):
        WebSocketMessage(source="user123", content="")


def test_websocket_event_source():
    """测试 WebSocketEventSource。"""
    source = WebSocketEventSource(user_id="user123")
    assert str(source) == "platform-ws:user123"
    assert source.platform_name == "websocket"


def test_websocket_event_source_from_string():
    """测试从字符串创建 WebSocketEventSource。"""
    source = WebSocketEventSource.from_string("platform-ws:user456")
    assert source.user_id == "user456"


@pytest.mark.asyncio
async def test_websocket_worker_init():
    """测试 WebSocketWorker 初始化。"""
    context = MagicMock()
    context.eventbus = MagicMock()

    worker = WebSocketWorker(context)

    assert worker.clients == set()
    # 验证订阅了两个事件类型
    assert context.eventbus.subscribe.call_count == 2


@pytest.mark.asyncio
async def test_websocket_worker_add_client():
    """测试添加客户端。"""
    from fastapi.websockets import WebSocketDisconnect

    context = MagicMock()
    context.eventbus = MagicMock()

    worker = WebSocketWorker(context)

    ws = MagicMock()
    added_during = []

    async def slow_receive():
        await asyncio.sleep(0.1)
        raise WebSocketDisconnect()

    ws.receive_json = slow_receive
    ws.accept = AsyncMock()

    async def check_clients():
        await asyncio.sleep(0.05)
        added_during.append(len(worker.clients))

    await asyncio.gather(
        worker.handle_connection(ws),
        check_clients(),
    )

    assert added_during == [1]


@pytest.mark.asyncio
async def test_websocket_worker_remove_client_on_disconnect():
    """测试客户端断开时移除。"""
    context = MagicMock()
    context.eventbus = MagicMock()

    worker = WebSocketWorker(context)

    ws = MagicMock()
    ws.receive_json = AsyncMock(side_effect=Exception("disconnect"))
    ws.close = AsyncMock()

    await worker.handle_connection(ws)

    assert len(worker.clients) == 0


@pytest.mark.asyncio
async def test_websocket_worker_broadcast_event():
    """测试广播事件给客户端。"""
    context = MagicMock()
    context.eventbus = MagicMock()

    worker = WebSocketWorker(context)

    # 创建模拟客户端
    ws = MagicMock()
    ws.send_json = AsyncMock()

    # 添加客户端
    worker.clients.add(ws)

    # 创建测试事件
    source = WebSocketEventSource(user_id="user123")
    event = OutboundEvent(session_id="sess-001", source=source, content="Hello")

    # 广播事件
    await worker.handle_event(event)

    # 验证发送
    ws.send_json.assert_called_once()
    call_args = ws.send_json.call_args[0][0]
    assert call_args["type"] == "OutboundEvent"
    assert call_args["content"] == "Hello"


@pytest.mark.asyncio
async def test_websocket_worker_no_clients_no_broadcast():
    """测试无客户端时不广播。"""
    context = MagicMock()
    context.eventbus = MagicMock()

    worker = WebSocketWorker(context)

    source = WebSocketEventSource(user_id="user123")
    event = OutboundEvent(session_id="sess-001", source=source, content="Hello")

    # 不添加客户端，直接广播
    await worker.handle_event(event)

    # 无断言，表示不抛异常即可


@pytest.mark.asyncio
async def test_websocket_worker_remove_failing_client():
    """测试移除发送失败的客户端。"""
    context = MagicMock()
    context.eventbus = MagicMock()

    worker = WebSocketWorker(context)

    # 创建失败的客户端
    ws = MagicMock()
    ws.send_json = AsyncMock(side_effect=Exception("send failed"))

    worker.clients.add(ws)
    assert len(worker.clients) == 1

    source = WebSocketEventSource(user_id="user123")
    event = OutboundEvent(session_id="sess-001", source=source, content="Hello")

    # 广播时客户端会被移除
    await worker.handle_event(event)

    assert len(worker.clients) == 0


@pytest.mark.asyncio
async def test_websocket_worker_validation_error():
    """测试客户端发送无效消息。"""
    context = MagicMock()
    context.eventbus = MagicMock()

    worker = WebSocketWorker(context)

    ws = MagicMock()
    ws.receive_json = AsyncMock(side_effect=[
        {"invalid": "data"},
        StopAsyncIteration(),
    ])
    ws.send_json = AsyncMock()

    await worker.handle_connection(ws)

    # 验证发送了错误消息
    ws.send_json.assert_called_once()
    error_msg = ws.send_json.call_args[0][0]
    assert error_msg["type"] == "error"
    assert "验证错误" in error_msg["message"]


@pytest.mark.asyncio
async def test_websocket_worker_publishes_event():
    """测试 WebSocket 消息发布 InboundEvent。"""
    context = MagicMock()
    context.eventbus = MagicMock()
    context.eventbus.publish = AsyncMock()

    # Mock config
    context.config = MagicMock()
    context.config.sources = {}
    context.config.default_agent = "pickle"
    context.config.set_runtime = MagicMock()

    # Mock agent_loader
    context.agent_loader = MagicMock()
    agent_def = MagicMock()
    context.agent_loader.load = MagicMock(return_value=agent_def)

    # Mock history_manager
    context.history_manager = MagicMock()
    context.history_manager.get_session_info = MagicMock(return_value={"agent_id": "pickle"})

    worker = WebSocketWorker(context)

    ws = MagicMock()
    ws.receive_json = AsyncMock(side_effect=[
        {"source": "user123", "content": "Hello"},
        Exception("stop"),
    ])
    ws.close = AsyncMock()

    await worker.handle_connection(ws)

    # 验证发布了事件
    context.eventbus.publish.assert_called_once()
    event = context.eventbus.publish.call_args[0][0]
    assert isinstance(event, InboundEvent)
    assert event.content == "Hello"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])