from __future__ import annotations
"""事件类测试。"""
import time
import pytest
from src.SmallShrimp.core.events import (
    Event, InboundEvent, OutboundEvent, serialize_event, deserialize_event,
    EventSource, CliEventSource
)


def test_event_source_base():
    """测试 EventSource 基类。"""
    source = CliEventSource()
    assert source.platform_name == "cli"
    assert source.is_platform
    assert source.is_cron is False
    assert source.is_agent is False


def test_event_source_from_string():
    """测试 EventSource 字符串解析。"""
    source = EventSource.from_string("platform-cli:cli-user")
    assert source.platform_name == "cli"


def test_cli_event_source():
    """测试 CLI EventSource。"""
    source = CliEventSource()
    assert str(source) == "platform-cli:cli-user"


def test_event_base():
    """测试基础事件类。"""
    source = CliEventSource()
    event = Event(session_id="sess-001", source=source, content="test")
    assert event.session_id == "sess-001"
    assert event.content == "test"
    assert event.timestamp > 0


def test_inbound_event_defaults():
    """测试入站事件默认值。"""
    source = CliEventSource()
    event = InboundEvent(session_id="sess-001", source=source, content="user input")
    assert event.retry_count == 0


def test_inbound_event_with_retry():
    """测试入站事件重试计数。"""
    source = CliEventSource()
    event = InboundEvent(session_id="sess-001", source=source, content="retry test", retry_count=3)
    assert event.retry_count == 3
    assert event.session_id == "sess-001"


def test_outbound_event():
    """测试出站事件。"""
    source = CliEventSource()
    event = OutboundEvent(session_id="sess-001", source=source, content="Agent response")
    assert event.content == "Agent response"
    assert event.error is None


def test_outbound_event_with_error():
    """测试带错误的出站事件。"""
    source = CliEventSource()
    event = OutboundEvent(
        session_id="sess-001",
        source=source,
        content="",
        error="Something went wrong"
    )
    assert event.error == "Something went wrong"


def test_event_serialization():
    """测试事件序列化/反序列化。"""
    source = CliEventSource()
    original = InboundEvent(
        session_id="sess-001",
        source=source,
        content="test content",
        retry_count=2
    )
    # 序列化
    data = serialize_event(original)
    assert data["type"] == "InboundEvent"
    assert data["session_id"] == "sess-001"
    assert data["content"] == "test content"
    assert data["retry_count"] == 2

    # 反序列化
    decoded = deserialize_event(data)
    assert decoded.session_id == "sess-001"
    assert decoded.content == "test content"
    assert isinstance(decoded, InboundEvent)


def test_event_round_trip():
    """测试事件的完整往返序列化。"""
    source = CliEventSource()
    event = OutboundEvent(
        session_id="sess-002",
        source=source,
        content="response content",
        error=None
    )
    data = serialize_event(event)
    decoded = deserialize_event(data)

    assert decoded.session_id == event.session_id
    assert decoded.content == event.content
    assert decoded.error == event.error
    assert type(decoded) == type(event)


def test_event_unknown_type():
    """测试未知事件类型反序列化。"""
    data = {"type": "UnknownEvent", "session_id": "sess-001"}
    with pytest.raises(ValueError):
        deserialize_event(data)


if __name__ == "__main__":
    test_event_source_base()
    test_event_source_from_string()
    test_cli_event_source()
    test_event_base()
    test_inbound_event_defaults()
    test_inbound_event_with_retry()
    test_outbound_event()
    test_outbound_event_with_error()
    test_event_serialization()
    test_event_round_trip()
    test_event_unknown_type()
    print("\nAll test_events tests passed!")