from __future__ import annotations
"""事件总线测试。"""
import asyncio
import pytest
from src.SmallShrimp.core.events import Event, OutboundEvent, InboundEvent


def test_event_base():
    """测试基础事件类。"""
    event = Event(session_id="sess-001", content="test")
    assert event.session_id == "sess-001"
    assert event.content == "test"
    assert event.timestamp > 0


def test_outbound_event():
    """测试出站事件。"""
    event = OutboundEvent(session_id="sess-001", content="Agent response")
    assert event.content == "Agent response"
    assert event.error is None


def test_outbound_event_with_error():
    """测试带错误的出站事件。"""
    event = OutboundEvent(
        session_id="sess-001",
        content="",
        error="Something went wrong"
    )
    assert event.error == "Something went wrong"


def test_event_serialization_roundtrip():
    """测试事件序列化往返。"""
    from src.SmallShrimp.core.events import serialize_event, deserialize_event

    original = OutboundEvent(session_id="sess-001", content="test content")
    data = serialize_event(original)
    decoded = deserialize_event(data)

    assert decoded.session_id == "sess-001"
    assert decoded.content == "test content"
    assert type(decoded) == type(original)


def test_event_unknown_type():
    """测试未知事件类型反序列化。"""
    from src.SmallShrimp.core.events import deserialize_event

    data = {"type": "UnknownEvent", "session_id": "sess-001"}
    with pytest.raises(ValueError):
        deserialize_event(data)


@pytest.mark.asyncio
async def test_eventbus_initialization():
    """测试事件总线初始化。"""
    from src.SmallShrimp.core.eventbus import EventBus

    bus = EventBus()
    assert bus._queue is not None
    assert len(bus._subscribers) == 0


@pytest.mark.asyncio
async def test_eventbus_subscribe():
    """测试订阅事件。"""
    from src.SmallShrimp.core.eventbus import EventBus

    bus = EventBus()
    call_count = []

    async def handler(event: OutboundEvent):
        call_count.append(1)

    bus.subscribe(OutboundEvent, handler)
    assert OutboundEvent in bus._subscribers
    assert len(bus._subscribers[OutboundEvent]) == 1


@pytest.mark.asyncio
async def test_eventbus_multiple_handlers():
    """测试多个处理器。"""
    from src.SmallShrimp.core.eventbus import EventBus

    bus = EventBus()
    counts = {"handler1": 0, "handler2": 0}

    async def handler1(event: OutboundEvent):
        counts["handler1"] += 1

    async def handler2(event: OutboundEvent):
        counts["handler2"] += 1

    bus.subscribe(OutboundEvent, handler1)
    bus.subscribe(OutboundEvent, handler2)

    assert len(bus._subscribers[OutboundEvent]) == 2


@pytest.mark.asyncio
async def test_eventbus_publish_and_dispatch():
    """测试发布和分发事件。"""
    from src.SmallShrimp.core.eventbus import EventBus

    bus = EventBus()
    received = []

    async def handler(event: OutboundEvent):
        received.append(event)

    bus.subscribe(OutboundEvent, handler)

    # 启动总线
    task = bus.start()

    # 发布事件
    event = OutboundEvent(session_id="sess-001", content="test")
    await bus.publish(event)

    # 等待处理
    await asyncio.sleep(0.2)

    # 停止总线
    await bus.stop()

    # 验证
    assert len(received) == 1
    assert received[0].session_id == "sess-001"


@pytest.mark.asyncio
async def test_eventbus_filtered_dispatch():
    """测试事件过滤分发。"""
    from src.SmallShrimp.core.eventbus import EventBus

    bus = EventBus()
    received_outbound = []
    received_inbound = []

    async def outbound_handler(event: OutboundEvent):
        received_outbound.append(event)

    async def inbound_handler(event: InboundEvent):
        received_inbound.append(event)

    bus.subscribe(OutboundEvent, outbound_handler)
    bus.subscribe(InboundEvent, inbound_handler)

    # 启动
    task = bus.start()

    # 只发布 OutboundEvent
    await bus.publish(OutboundEvent(session_id="sess-001", content="out"))
    await bus.publish(OutboundEvent(session_id="sess-002", content="out2"))

    await asyncio.sleep(0.2)

    # 停止
    await bus.stop()

    assert len(received_outbound) == 2
    assert len(received_inbound) == 0


@pytest.mark.asyncio
async def test_eventbus_multiple_events():
    """测试多个事件处理。"""
    from src.SmallShrimp.core.eventbus import EventBus

    bus = EventBus()
    received = []

    async def handler(event: OutboundEvent):
        received.append(event)

    bus.subscribe(OutboundEvent, handler)

    task = bus.start()

    # 发布多个事件
    for i in range(5):
        await bus.publish(OutboundEvent(session_id=f"sess-{i}", content=f"msg-{i}"))

    await asyncio.sleep(0.3)
    await bus.stop()

    assert len(received) == 5


if __name__ == "__main__":
    # 同步测试
    test_event_base()
    test_outbound_event()
    test_outbound_event_with_error()
    test_event_serialization_roundtrip()
    test_event_unknown_type()

    # 异步测试
    asyncio.run(test_eventbus_initialization())
    asyncio.run(test_eventbus_subscribe())
    asyncio.run(test_eventbus_multiple_handlers())
    asyncio.run(test_eventbus_publish_and_dispatch())
    asyncio.run(test_eventbus_filtered_dispatch())
    asyncio.run(test_eventbus_multiple_events())

    print("\nAll test_eventbus tests passed!")