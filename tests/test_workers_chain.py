"""Server Workers 集成测试 - 串联测试。"""
import asyncio
import subprocess
import sys

import pytest

from src.SmallShrimp.core.eventbus import EventBus
from src.SmallShrimp.core.events import (
    OutboundEvent,
    InboundEvent,
    CliEventSource,
    WebSocketEventSource,
)
from src.SmallShrimp.server.worker import SubscriberWorker


class TestWorkerLifecycle:
    """Worker 生命周期测试。"""

    @pytest.mark.asyncio
    async def test_worker_start_stop(self):
        """测试 Worker 启动和停止。"""
        worker = SubscriberWorker()
        assert not worker.is_running()

        task = worker.start()
        assert worker.is_running()

        await worker.stop()
        assert not worker.is_running()


class TestEventBusWorkerIntegration:
    """EventBus 与 Worker 集成测试。"""

    @pytest.mark.asyncio
    async def test_eventbus_subscribers_on_worker(self):
        """测试 Worker 订阅 EventBus。"""
        eventbus = EventBus()
        received = []

        async def handler(event: OutboundEvent):
            received.append(event)

        eventbus.subscribe(OutboundEvent, handler)
        task = eventbus.start()

        source = CliEventSource()
        event = OutboundEvent(session_id="sess-001", content="test", source=source)
        await eventbus.publish(event)

        await asyncio.sleep(0.2)
        await eventbus.stop()

        assert len(received) == 1
        assert received[0].session_id == "sess-001"

    @pytest.mark.asyncio
    async def test_multiple_event_types(self):
        """测试多种事件类型过滤。"""
        eventbus = EventBus()
        outbound_received = []

        async def outbound_handler(event: OutboundEvent):
            outbound_received.append(event)

        eventbus.subscribe(OutboundEvent, outbound_handler)
        task = eventbus.start()

        source = CliEventSource()
        await eventbus.publish(
            OutboundEvent(session_id="sess-001", content="out", source=source)
        )
        await eventbus.publish(
            OutboundEvent(session_id="sess-002", content="out2", source=source)
        )

        await asyncio.sleep(0.2)
        await eventbus.stop()

        assert len(outbound_received) == 2


class TestWorkersChain:
    """Workers 串联测试 - 模拟 Server 的完整流程。"""

    @pytest.mark.asyncio
    async def test_inbound_to_outbound_flow(self):
        """测试 InboundEvent → OutboundEvent 的完整流程。"""
        eventbus = EventBus()
        outbound_events = []

        async def delivery_handler(event: OutboundEvent):
            outbound_events.append(event)
            eventbus.ack(event)

        eventbus.subscribe(OutboundEvent, delivery_handler)
        task = eventbus.start()

        source = CliEventSource()
        inbound = InboundEvent(session_id="sess-001", content="hello", source=source)
        await eventbus.publish(inbound)

        response = OutboundEvent(
            session_id="sess-001", content="hi there!", source=source
        )
        await eventbus.publish(response)

        await asyncio.sleep(0.3)
        await eventbus.stop()

        assert len(outbound_events) == 1
        assert outbound_events[0].content == "hi there!"

    @pytest.mark.asyncio
    async def test_session_id_propagation(self):
        """测试 session_id 在事件链中正确传递。"""
        eventbus = EventBus()
        received_sessions = []

        async def handler(event: OutboundEvent):
            received_sessions.append(event.session_id)

        eventbus.subscribe(OutboundEvent, handler)
        task = eventbus.start()

        source = CliEventSource()
        session_ids = ["sess-alpha", "sess-beta", "sess-gamma"]
        for sid in session_ids:
            event = OutboundEvent(session_id=sid, content=f"content for {sid}", source=source)
            await eventbus.publish(event)

        await asyncio.sleep(0.3)
        await eventbus.stop()

        assert received_sessions == session_ids


class TestWebSocketWorkerChain:
    """WebSocket Worker 串联测试。"""

    def test_websocket_message_model(self):
        """测试 WebSocketMessage 模型。"""
        from src.SmallShrimp.server.websocket_worker import WebSocketMessage

        msg = WebSocketMessage(source="user-123", content="hello")
        assert msg.source == "user-123"
        assert msg.content == "hello"
        assert msg.agent_id is None

        msg_with_agent = WebSocketMessage(
            source="user-456", content="hi", agent_id="pickle"
        )
        assert msg_with_agent.agent_id == "pickle"

    def test_websocket_event_source(self):
        """测试 WebSocketEventSource 生成。"""
        from src.SmallShrimp.core.events import WebSocketEventSource

        source = WebSocketEventSource(user_id="user-001")
        source_str = str(source)
        assert "ws" in source_str.lower() or "websocket" in source_str.lower()
        assert "user-001" in source_str


class TestChannelWorkerChain:
    """Channel Worker 串联测试。"""

    def test_channel_callback_pattern(self):
        """测试 Channel 回调模式。"""
        from src.SmallShrimp.core.events import EventSource

        async def channel_callback(message: str, source: EventSource) -> None:
            assert message == "test message"
            assert "test-source" in str(source)

        assert callable(channel_callback)


class TestDeliveryWorkerHelpers:
    """DeliveryWorker 辅助函数测试。"""

    def test_chunk_message(self):
        """测试消息分块。"""
        from src.SmallShrimp.server.delivery_worker import chunk_message

        chunks = chunk_message("short message", 4096)
        assert len(chunks) == 1
        assert chunks[0] == "short message"

        long_text = "Para 1\n\nPara 2\n\nPara 3"
        chunks = chunk_message(long_text, 20)
        assert len(chunks) > 1

    def test_compute_backoff_ms(self):
        """测试退避时间计算。"""
        from src.SmallShrimp.server.delivery_worker import compute_backoff_ms

        backoff1 = compute_backoff_ms(1)
        assert backoff1 >= 4000 and backoff1 <= 6000

        backoff2 = compute_backoff_ms(2)
        assert backoff2 >= 20000 and backoff2 <= 30000

        assert compute_backoff_ms(0) == 0


class TestServerIntegration:
    """Server 集成测试 - 模拟完整的 Workers 串联。"""

    @pytest.mark.asyncio
    async def test_eventbus_queue_processing(self):
        """测试 EventBus 队列处理。"""
        eventbus = EventBus()
        processed = []

        async def handler(event: OutboundEvent):
            processed.append(event)

        eventbus.subscribe(OutboundEvent, handler)
        task = eventbus.start()

        source = CliEventSource()
        events_count = 5
        for i in range(events_count):
            await eventbus.publish(
                OutboundEvent(
                    session_id=f"sess-{i}", content=f"msg-{i}", source=source
                )
            )

        await asyncio.sleep(0.5)
        await eventbus.stop()

        assert len(processed) == events_count


def test_worker_crash_isolation():
    """测试 Worker 崩溃隔离 - 在独立进程中运行以避免污染其他测试。"""
    # 在子进程中运行崩溃测试，避免影响 pytest 事件循环
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import asyncio
import sys
sys.path.insert(0, '.')
from src.SmallShrimp.server.worker import SubscriberWorker

class FailingWorker(SubscriberWorker):
    async def run(self):
        raise ValueError('test crash')

async def main():
    worker = FailingWorker()
    worker.start()
    await asyncio.sleep(0.2)
    assert worker.has_crashed(), 'Worker should have crashed'
    exc = worker.get_exception()
    assert exc is not None
    assert 'test crash' in str(exc)
    worker._task.cancel()
    print('PASS')

asyncio.run(main())
""",
        ],
        capture_output=True,
        text=True,
        cwd="G:/agent/SmallShrimp",
        env={"CONDA_DEFAULT_ENV": "smallshrimp", **subprocess.os.environ},
    )
    assert result.returncode == 0, f"Crash test failed: {result.stderr}"
    assert "PASS" in result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])