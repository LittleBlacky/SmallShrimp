from __future__ import annotations
"""并行工具执行测试。"""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_parallel_readonly_tools():
    """只读工具并行执行，写工具串行执行。"""
    from src.SmallShrimp.core.agent import Agent, AgentSession
    from src.SmallShrimp.core.session_state import SessionState

    # 构造 Agent，tool_registry 记录执行顺序
    registry = MagicMock()
    exec_order = []

    async def mock_execute(name, **kwargs):
        exec_order.append(name)
        if name == "grep":
            await asyncio.sleep(0.1)  # 慢工具
        return f"result:{name}"

    registry.execute_tool = AsyncMock(side_effect=mock_execute)
    registry.get_schemas = MagicMock(return_value=[])

    agent = MagicMock()
    agent.tool_registry = registry
    agent.context_guard = MagicMock()
    agent.context_guard.check_and_compact = AsyncMock(return_value=MagicMock())
    agent.context_guard.estimate_tokens = MagicMock(return_value=10)
    agent.context_guard.token_threshold = 100000
    agent.agent_def = MagicMock()
    agent.agent_def.llm = {"model": "gpt-4"}
    agent.agent_def.tools = []
    agent.history_manager = None

    state = SessionState(session_id="test", agent=agent, messages=[])
    session = AgentSession(agent=agent, state=state)

    tool_calls = [
        {"id": "1", "function": {"name": "read", "arguments": '{"path":"a.txt"}'}},
        {"id": "2", "function": {"name": "grep", "arguments": '{"pattern":"x"}'}},
        {"id": "3", "function": {"name": "glob", "arguments": '{"pattern":"*.py"}'}},
        {"id": "4", "function": {"name": "write", "arguments": '{"path":"b.txt","content":"x"}'}},
    ]

    await session._execute_tool_calls(tool_calls)

    # read, grep, glob 应该并行执行的（grep 慢但不会阻塞 read/glob）
    # write 必须在最后
    assert len(exec_order) == 4
    assert exec_order[3] == "write"
    # grep 因为是慢的，先执行完的是 read 或 glob
    assert "read" in exec_order[:3]
    assert "glob" in exec_order[:3]


@pytest.mark.asyncio
async def test_parallel_tools_time():
    """并行执行比串行快。"""
    from src.SmallShrimp.core.agent import Agent, AgentSession
    from src.SmallShrimp.core.session_state import SessionState

    registry = MagicMock()

    async def slow_tool(name, **kwargs):
        await asyncio.sleep(0.05)
        return f"result:{name}"

    registry.execute_tool = AsyncMock(side_effect=slow_tool)
    registry.get_schemas = MagicMock(return_value=[])

    agent = MagicMock()
    agent.tool_registry = registry
    agent.context_guard = MagicMock()
    agent.context_guard.check_and_compact = AsyncMock(return_value=MagicMock())
    agent.context_guard.estimate_tokens = MagicMock(return_value=10)
    agent.context_guard.token_threshold = 100000
    agent.agent_def = MagicMock()
    agent.agent_def.llm = {"model": "gpt-4"}
    agent.agent_def.tools = []
    agent.history_manager = None

    state = SessionState(session_id="test", agent=agent, messages=[])
    session = AgentSession(agent=agent, state=state)

    tool_calls = [
        {"id": str(i), "function": {"name": "read", "arguments": '{"path":"x"}'}}
        for i in range(4)
    ]

    t0 = time.time()
    await session._execute_tool_calls(tool_calls)
    elapsed = time.time() - t0

    # 4 个并行 0.05s 任务，并行应 ~0.05s，串行应 ~0.2s
    assert elapsed < 0.15, f"并行执行应快于串行，实际 {elapsed:.2f}s"


if __name__ == "__main__":
    asyncio.run(test_parallel_readonly_tools())
    asyncio.run(test_parallel_tools_time())
    print("\nAll parallel tools tests passed!")
