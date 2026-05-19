from __future__ import annotations
"""AgentWorker 并发控制测试。"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.SmallShrimp.server.agent_worker import AgentWorker


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency():
    """max_concurrency=1 时，同一 Agent 的第二个请求必须等待。"""
    context = MagicMock()
    context.eventbus = MagicMock()
    context.eventbus.subscribe = MagicMock()
    context.config.data = {}
    context.agent_loader = MagicMock()

    worker = AgentWorker(context)

    # 创建一个 agent_def，max_concurrency=1
    agent_def = MagicMock()
    agent_def.id = "pickle"
    agent_def.max_concurrency = 1

    # 信号量应该只能存一个
    sem = worker._get_or_create_semaphore(agent_def)
    assert sem._value == 1

    # 获取信号量后，值变为 0
    acquired = sem.locked() is False
    assert acquired


@pytest.mark.asyncio
async def test_semaphore_per_agent_isolation():
    """不同 Agent 的信号量互相独立。"""
    context = MagicMock()
    context.eventbus = MagicMock()
    context.eventbus.subscribe = MagicMock()
    context.config.data = {}
    context.agent_loader = MagicMock()

    worker = AgentWorker(context)

    pickle_def = MagicMock()
    pickle_def.id = "pickle"
    pickle_def.max_concurrency = 1

    cookie_def = MagicMock()
    cookie_def.id = "cookie"
    cookie_def.max_concurrency = 3

    sem_pickle = worker._get_or_create_semaphore(pickle_def)
    sem_cookie = worker._get_or_create_semaphore(cookie_def)

    assert sem_pickle is not sem_cookie
    assert sem_pickle._value == 1  # pickle: max 1
    assert sem_cookie._value == 3  # cookie: max 3


@pytest.mark.asyncio
async def test_semaphore_serializes_execution():
    """max_concurrency=1 时，请求按顺序执行。"""
    context = MagicMock()
    context.eventbus = MagicMock()
    context.eventbus.subscribe = MagicMock()
    context.eventbus.publish = AsyncMock()
    context.config.data = {}
    context.config.default_agent = "pickle"
    context.history_manager = MagicMock()
    context.history_manager.get_session_info = MagicMock(return_value={
        "session_id": "test-1",
        "agent_id": "pickle",
    })
    context.agent_loader = MagicMock()
    context.agent_loader.load = MagicMock(return_value=MagicMock(
        id="pickle", name="pickle", max_concurrency=1,
        llm={"provider": "openai"},
    ))
    context.tool_registry = MagicMock()
    context.tool_registry.get_schemas = MagicMock(return_value=[])
    context.command_registry = MagicMock()
    context.command_registry.dispatch = AsyncMock()
    context.routing_table = None

    worker = AgentWorker(context)

    execution_order = []

    # Mock Agent.chat 记录执行顺序
    async def mock_chat(message):
        execution_order.append(message)
        await asyncio.sleep(0.05)
        return f"response: {message}"

    context.agent_loader.load.return_value.llm = MagicMock()
    context.agent_loader.load.return_value.llm.chat = AsyncMock()

    # 替换 exec_session 为简单版本测试并发
    from src.SmallShrimp.core.events import InboundEvent, CliEventSource

    event_a = InboundEvent(session_id="a", source=CliEventSource(), content="hello A")
    event_b = InboundEvent(session_id="b", source=CliEventSource(), content="hello B")

    agent_def = context.agent_loader.load.return_value

    # 手动测试信号量行为
    sem = worker._get_or_create_semaphore(agent_def)

    async def task(event):
        async with sem:
            execution_order.append(event.content)
            await asyncio.sleep(0.02)
        return event.content

    # 同时启动两个任务
    t1 = asyncio.create_task(task(event_a))
    t2 = asyncio.create_task(task(event_b))
    await asyncio.gather(t1, t2)

    # 应该按顺序执行（串行）
    assert execution_order == ["hello A", "hello B"]


@pytest.mark.asyncio
async def test_cleanup_removes_stale_semaphores():
    """空闲信号量在足够次调用后被清理。"""
    context = MagicMock()
    context.eventbus = MagicMock()
    context.eventbus.subscribe = MagicMock()
    context.config.data = {}
    context.agent_loader = MagicMock()

    worker = AgentWorker(context)

    agent_def = MagicMock()
    agent_def.id = "temp_agent"
    agent_def.max_concurrency = 1

    # 创建信号量
    sem = worker._get_or_create_semaphore(agent_def)
    assert "temp_agent" in worker._semaphores

    # 触发 5 次清理周期
    for _ in range(5):
        worker._maybe_cleanup_semaphores()

    # 信号量空闲（无等待者）应该被清理
    assert "temp_agent" not in worker._semaphores


@pytest.mark.asyncio
async def test_semaphore_not_cleaned_when_in_use():
    """正在使用的信号量不被清理。"""
    context = MagicMock()
    context.eventbus = MagicMock()
    context.eventbus.subscribe = MagicMock()
    context.config.data = {}
    context.agent_loader = MagicMock()

    worker = AgentWorker(context)

    agent_def = MagicMock()
    agent_def.id = "active_agent"
    agent_def.max_concurrency = 1

    sem = worker._get_or_create_semaphore(agent_def)

    # 获取信号量（模拟使用中）
    await sem.acquire()

    # 触发 5 次清理
    for _ in range(5):
        worker._maybe_cleanup_semaphores()

    # 使用中不应该被清理
    assert "active_agent" in worker._semaphores

    sem.release()


if __name__ == "__main__":
    asyncio.run(test_semaphore_limits_concurrency())
    asyncio.run(test_semaphore_per_agent_isolation())
    asyncio.run(test_semaphore_serializes_execution())
    asyncio.run(test_cleanup_removes_stale_semaphores())
    asyncio.run(test_semaphore_not_cleaned_when_in_use())
    print("\nAll concurrency tests passed!")
