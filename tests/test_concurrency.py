from __future__ import annotations
"""AgentWorker 并发控制测试 — 按用户。"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.SmallShrimp.server.agent_worker import AgentWorker


@pytest.mark.asyncio
async def test_semaphore_limits_per_user():
    """同一用户的第二个请求必须等待。"""
    context = MagicMock()
    context.eventbus = MagicMock()
    context.eventbus.subscribe = MagicMock()
    context.config.data = {}
    context.agent_loader = MagicMock()

    worker = AgentWorker(context)

    sem = worker._get_or_create_semaphore("platform-telegram:123", limit=1)
    assert sem._value == 1


@pytest.mark.asyncio
async def test_semaphore_per_user_isolation():
    """不同用户的信号量互相独立。"""
    context = MagicMock()
    context.eventbus = MagicMock()
    context.eventbus.subscribe = MagicMock()
    context.config.data = {}
    context.agent_loader = MagicMock()

    worker = AgentWorker(context)

    sem_alice = worker._get_or_create_semaphore("platform-telegram:alice", limit=1)
    sem_bob = worker._get_or_create_semaphore("platform-telegram:bob", limit=3)

    assert sem_alice is not sem_bob
    assert sem_alice._value == 1
    assert sem_bob._value == 3


@pytest.mark.asyncio
async def test_semaphore_serializes_execution():
    """同一用户的多请求串行执行。"""
    context = MagicMock()
    context.eventbus = MagicMock()
    context.eventbus.subscribe = MagicMock()
    context.config.data = {}
    context.agent_loader = MagicMock()

    worker = AgentWorker(context)

    execution_order = []

    sem = worker._get_or_create_semaphore("user-x", limit=1)

    async def task(event_id):
        async with sem:
            execution_order.append(event_id)
            await asyncio.sleep(0.02)

    t1 = asyncio.create_task(task("A"))
    t2 = asyncio.create_task(task("B"))
    await asyncio.gather(t1, t2)

    assert execution_order == ["A", "B"]


@pytest.mark.asyncio
async def test_cleanup_removes_stale_semaphores():
    """空闲信号量在足够次调用后被清理。"""
    context = MagicMock()
    context.eventbus = MagicMock()
    context.eventbus.subscribe = MagicMock()
    context.config.data = {}
    context.agent_loader = MagicMock()

    worker = AgentWorker(context)
    worker._get_or_create_semaphore("temp-user", limit=3)

    assert "temp-user" in worker._semaphores

    for _ in range(5):
        worker._maybe_cleanup_semaphores()

    assert "temp-user" not in worker._semaphores


@pytest.mark.asyncio
async def test_semaphore_not_cleaned_when_in_use():
    """使用中的信号量不被清理。"""
    context = MagicMock()
    context.eventbus = MagicMock()
    context.eventbus.subscribe = MagicMock()
    context.config.data = {}
    context.agent_loader = MagicMock()

    worker = AgentWorker(context)
    sem = worker._get_or_create_semaphore("active-user", limit=3)

    await sem.acquire()

    for _ in range(5):
        worker._maybe_cleanup_semaphores()

    assert "active-user" in worker._semaphores
    sem.release()


if __name__ == "__main__":
    asyncio.run(test_semaphore_limits_per_user())
    asyncio.run(test_semaphore_per_user_isolation())
    asyncio.run(test_semaphore_serializes_execution())
    asyncio.run(test_cleanup_removes_stale_semaphores())
    asyncio.run(test_semaphore_not_cleaned_when_in_use())
    print("\nAll concurrency tests passed!")
