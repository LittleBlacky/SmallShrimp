from __future__ import annotations
"""Agent 调度测试。"""
import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.SmallShrimp.core.events.events import (
    AgentEventSource, DispatchEvent, DispatchResultEvent,
    CliEventSource, InboundEvent,
)
from src.SmallShrimp.core.hooks import HookManager, HookPoint, HookResult


def test_agent_event_source_str():
    """AgentEventSource 序列化为 agent:id 格式。"""
    source = AgentEventSource(agent_id="pickle")
    assert str(source) == "agent:pickle"
    assert source.is_agent
    assert not source.is_platform
    assert not source.is_cron


def test_agent_event_source_from_string():
    """从字符串反序列化 AgentEventSource。"""
    source = AgentEventSource.from_string("agent:pickle")
    assert source.agent_id == "pickle"


def test_dispatch_event_fields():
    """DispatchEvent 包含 parent_session_id。"""
    source = AgentEventSource(agent_id="pickle")
    event = DispatchEvent(
        session_id="sub-1",
        source=source,
        content="Remember user name",
        parent_session_id="main-1",
    )
    assert event.parent_session_id == "main-1"
    assert event.retry_count == 0


def test_dispatch_result_event():
    """DispatchResultEvent 可带 error。"""
    source = AgentEventSource(agent_id="cookie")
    event = DispatchResultEvent(
        session_id="sub-1",
        source=source,
        content="Done",
    )
    assert event.error is None

    error_event = DispatchResultEvent(
        session_id="sub-1",
        source=source,
        content="",
        error="Agent not found",
    )
    assert error_event.error == "Agent not found"


def test_event_serialization_roundtrip():
    """DispatchEvent 可序列化/反序列化。"""
    source = AgentEventSource(agent_id="pickle")
    event = DispatchEvent(
        session_id="sub-1",
        source=source,
        content="task",
        parent_session_id="main-1",
    )
    data = event.to_dict()
    assert data["type"] == "DispatchEvent"
    assert data["source"] == "agent:pickle"


@pytest.mark.asyncio
async def test_agent_worker_handles_dispatch_event():
    """AgentWorker 订阅并处理 DispatchEvent。"""
    from src.SmallShrimp.server.workers.agent import AgentWorker
    from src.SmallShrimp.core.events.events import DispatchEvent, AgentEventSource

    context = MagicMock()
    context.eventbus = MagicMock()
    context.eventbus.subscribe = MagicMock()
    context.eventbus.publish = AsyncMock()
    context.config = MagicMock()
    context.config.data = {}
    context.config.default_agent = "cookie"
    context.history_manager = MagicMock()
    context.history_manager.get_session_info = MagicMock(return_value={
        "session_id": "sub-1",
        "agent_id": "cookie",
    })
    context.agent_loader = MagicMock()
    context.agent_loader.load = MagicMock()
    context.tool_registry = MagicMock()
    context.tool_registry.get_schemas = MagicMock(return_value=[])
    context.command_registry = MagicMock()
    context.routing_table = None

    worker = AgentWorker(context)

    # 验证 AgentWorker 订阅了 DispatchEvent
    subscribe_calls = context.eventbus.subscribe.call_args_list
    subscribed_types = [call[0][0] for call in subscribe_calls]
    assert DispatchEvent in subscribed_types


@pytest.mark.asyncio
async def test_subagent_tool_returns_none_when_no_agents():
    """只有一个 Agent 时，subagent_dispatch 工具返回 None。"""
    from src.SmallShrimp.tools.subagent_tool import create_subagent_dispatch_tool

    context = MagicMock()
    context.agent_loader.discover_agents = MagicMock(return_value=[
        MagicMock(id="pickle", name="pickle")
    ])

    tool = create_subagent_dispatch_tool("pickle", context)
    assert tool is None


@pytest.mark.asyncio
async def test_subagent_tool_creates_tool_when_agents_available():
    """有多个 Agent 时，创建 subagent_dispatch 工具。"""
    from src.SmallShrimp.tools.subagent_tool import create_subagent_dispatch_tool

    context = MagicMock()
    context.agent_loader.discover_agents = MagicMock(return_value=[
        MagicMock(id="pickle", name="pickle"),
        MagicMock(id="cookie", name="cookie"),
    ])

    tool = create_subagent_dispatch_tool("pickle", context)
    assert tool is not None
    assert tool.name == "subagent_dispatch"


@pytest.mark.asyncio
async def test_subagent_dispatch_tool_publishes_event():
    """subagent_dispatch 直接调用子 Agent run_once。"""
    from src.SmallShrimp.tools.subagent_tool import create_subagent_dispatch_tool
    from src.SmallShrimp.core.runtime.agent import AgentResult

    context = MagicMock()
    context.agent_loader.discover_agents = MagicMock(return_value=[
        MagicMock(id="pickle", name="pickle"),
        MagicMock(id="cookie", name="cookie", description="Memory manager"),
    ])
    context.agent_loader.load = MagicMock(return_value=MagicMock(
        id="cookie", name="cookie", llm={"provider": "openai", "model": "openai/gpt-5.5"},
    ))
    context.config = MagicMock()
    context.config.data = {}
    context.config.get_default_provider = MagicMock(return_value="openai")
    context.config.get_provider_config = MagicMock(return_value={
        "api_key": "test-key",
        "api_base": "https://example.test/v1",
    })
    context.config.on_change = MagicMock()
    context.tool_registry = MagicMock()
    context.tool_registry.get_schemas = MagicMock(return_value=[])
    context.history_manager = MagicMock()
    context.prompt_builder = None
    context.memory_manager = None
    context.eventbus = MagicMock()

    tool = create_subagent_dispatch_tool("pickle", context)

    from types import SimpleNamespace

    session = SimpleNamespace()
    session.session_id = "main-session"

    with patch("src.SmallShrimp.core.runtime.agent.AgentSession.run_once", new_callable=AsyncMock) as run_once:
        run_once.return_value = AgentResult(
            text="已记住用户偏好",
            input_tokens=10,
            output_tokens=5,
            session_id="sub-session",
        )

        result = await tool.call(agent_id="cookie", task="记住用户偏好 Python", session=session)

    assert "已记住用户偏好" in result.content
    run_once.assert_awaited_once()
    assert session._subagent_tokens == 15


@pytest.mark.asyncio
async def test_subagent_dispatch_emits_started_and_completed_hooks():
    """subagent_dispatch emits lifecycle hooks around run_once."""
    from src.SmallShrimp.tools.subagent_tool import create_subagent_dispatch_tool
    from src.SmallShrimp.core.runtime.agent import AgentResult

    context = MagicMock()
    context.agent_loader.discover_agents = MagicMock(return_value=[
        MagicMock(id="pickle", name="pickle"),
        MagicMock(id="cookie", name="cookie", description="Memory manager"),
    ])
    context.agent_loader.load = MagicMock(return_value=MagicMock(
        id="cookie", name="cookie", llm={"provider": "openai", "model": "openai/gpt-5.5"},
    ))
    context.config = MagicMock()
    context.config.data = {}
    context.config.get_default_provider = MagicMock(return_value="openai")
    context.config.get_provider_config = MagicMock(return_value={
        "api_key": "test-key",
        "api_base": "https://example.test/v1",
    })
    context.config.on_change = MagicMock()
    context.tool_registry = MagicMock()
    context.tool_registry.get_schemas = MagicMock(return_value=[])
    context.history_manager = MagicMock()
    context.prompt_builder = None
    context.memory_manager = None

    tool = create_subagent_dispatch_tool("pickle", context)
    session = SimpleNamespace()
    session.session_id = "main-session"
    session.state = MagicMock()
    session.agent = MagicMock()
    session.agent.agent_def = MagicMock(id="pickle", name="pickle")
    session.hooks = HookManager()
    seen = []

    async def record(ctx):
        seen.append(ctx)
        return HookResult.observe()

    session.hooks.register(HookPoint.SUBAGENT_STARTED, record, name="started")
    session.hooks.register(HookPoint.SUBAGENT_COMPLETED, record, name="completed")

    with patch("src.SmallShrimp.core.runtime.agent.AgentSession.run_once", new_callable=AsyncMock) as run_once:
        run_once.return_value = AgentResult(
            text="done",
            input_tokens=10,
            output_tokens=5,
            session_id="sub-session",
        )

        result = await tool.call(agent_id="cookie", task="记住用户偏好 Python", session=session)

    assert "done" in result.content
    assert [ctx.hook_point for ctx in seen] == [
        HookPoint.SUBAGENT_STARTED,
        HookPoint.SUBAGENT_COMPLETED,
    ]
    assert seen[0].session_id == "main-session"
    assert seen[0].agent_id == "pickle"
    assert seen[0].state is session.state
    assert seen[0].metadata == {
        "subagent_id": "cookie",
        "task": "记住用户偏好 Python",
        "agent_type": "general",
    }
    assert seen[1].metadata == {
        "subagent_id": "cookie",
        "task": "记住用户偏好 Python",
        "agent_type": "general",
        "subagent_session_id": "sub-session",
        "input_tokens": 10,
        "output_tokens": 5,
    }
    run_once.assert_awaited_once()
    assert session._subagent_tokens == 15


@pytest.mark.asyncio
async def test_subagent_hook_failure_does_not_break_successful_dispatch():
    """subagent_dispatch succeeds even when observe-only hooks fail."""
    from src.SmallShrimp.tools.subagent_tool import create_subagent_dispatch_tool
    from src.SmallShrimp.core.runtime.agent import AgentResult

    context = MagicMock()
    context.agent_loader.discover_agents = MagicMock(return_value=[
        MagicMock(id="pickle", name="pickle"),
        MagicMock(id="cookie", name="cookie", description="Memory manager"),
    ])
    context.agent_loader.load = MagicMock(return_value=MagicMock(
        id="cookie", name="cookie", llm={"provider": "openai", "model": "openai/gpt-5.5"},
    ))
    context.config = MagicMock()
    context.config.data = {}
    context.config.get_default_provider = MagicMock(return_value="openai")
    context.config.get_provider_config = MagicMock(return_value={
        "api_key": "test-key",
        "api_base": "https://example.test/v1",
    })
    context.config.on_change = MagicMock()
    context.tool_registry = MagicMock()
    context.tool_registry.get_schemas = MagicMock(return_value=[])
    context.history_manager = MagicMock()
    context.prompt_builder = None
    context.memory_manager = None

    tool = create_subagent_dispatch_tool("pickle", context)
    session = SimpleNamespace()
    session.session_id = "main-session"
    session.state = MagicMock()
    session.agent = MagicMock()
    session.agent.agent_def = MagicMock(id="pickle", name="pickle")
    session.hooks = HookManager()

    async def broken(ctx):
        raise RuntimeError("hook failed")

    session.hooks.register(HookPoint.SUBAGENT_STARTED, broken, name="broken_started", critical=True)
    session.hooks.register(HookPoint.SUBAGENT_COMPLETED, broken, name="broken_completed", critical=True)

    with patch("src.SmallShrimp.core.runtime.agent.AgentSession.run_once", new_callable=AsyncMock) as run_once:
        run_once.return_value = AgentResult(
            text="done",
            input_tokens=10,
            output_tokens=5,
            session_id="sub-session",
        )

        result = await tool.call(agent_id="cookie", task="记住用户偏好 Python", session=session)

    assert "done" in result.content
    run_once.assert_awaited_once()
    assert session._subagent_tokens == 15


if __name__ == "__main__":
    test_agent_event_source_str()
    test_agent_event_source_from_string()
    test_dispatch_event_fields()
    test_dispatch_result_event()
    test_event_serialization_roundtrip()
    asyncio.run(test_agent_worker_handles_dispatch_event())
    asyncio.run(test_subagent_tool_returns_none_when_no_agents())
    asyncio.run(test_subagent_tool_creates_tool_when_agents_available())
    asyncio.run(test_subagent_dispatch_tool_publishes_event())
    print("\nAll test_dispatch tests passed!")

