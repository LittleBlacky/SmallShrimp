from __future__ import annotations
"""ContextGuard 测试。"""
import pytest
from unittest.mock import AsyncMock, MagicMock


def test_context_guard_init():
    """测试 ContextGuard 初始化。"""
    from src.SmallShrimp.core.context_guard import ContextGuard

    guard = ContextGuard(token_threshold=100000)
    assert guard.token_threshold == 100000


def test_context_guard_default_threshold():
    """测试默认阈值。"""
    from src.SmallShrimp.core.context_guard import ContextGuard

    guard = ContextGuard()
    assert guard.token_threshold == 160000  # 80% of 200k


def test_truncate_large_tool_results():
    """测试工具结果截断。"""
    from src.SmallShrimp.core.context_guard import ContextGuard, MAX_TOOL_RESULT_CHARS
    from src.SmallShrimp.core.message import HumanMessage, ToolMessage

    guard = ContextGuard()

    small_content = "Normal result"
    large_content = "x" * (MAX_TOOL_RESULT_CHARS + 1000)

    messages = [
        HumanMessage(content="Hello"),
        ToolMessage(content=large_content, tool_call_id="call1", name="test"),
    ]

    truncated = guard._truncate_large_tool_results(messages)

    assert len(truncated) == 2
    assert truncated[0].content == "Hello"
    assert len(truncated[1].content) < len(large_content)
    assert "[truncated]" in truncated[1].content


def test_truncate_preserves_small_results():
    """测试小结果不会被截断。"""
    from src.SmallShrimp.core.context_guard import ContextGuard
    from src.SmallShrimp.core.message import ToolMessage

    guard = ContextGuard()

    messages = [
        ToolMessage(content="Small result", tool_call_id="call1", name="test"),
    ]

    truncated = guard._truncate_large_tool_results(messages)

    assert len(truncated) == 1
    assert truncated[0].content == "Small result"


def test_truncate_non_tool_messages():
    """测试非工具消息不被截断。"""
    from src.SmallShrimp.core.context_guard import ContextGuard
    from src.SmallShrimp.core.message import HumanMessage, AssistantMessage

    guard = ContextGuard()

    messages = [
        HumanMessage(content="User message"),
        AssistantMessage(content="Assistant response"),
    ]

    truncated = guard._truncate_large_tool_results(messages)

    assert len(truncated) == 2
    assert truncated[0].content == "User message"
    assert truncated[1].content == "Assistant response"


@pytest.mark.asyncio
async def test_check_and_compact_under_threshold():
    """测试未超阈值时直接返回。"""
    from src.SmallShrimp.core.context_guard import ContextGuard
    from src.SmallShrimp.core.message import HumanMessage, AssistantMessage

    guard = ContextGuard(token_threshold=100000)

    state = MagicMock()
    state.messages = [
        HumanMessage(content="Hello"),
        AssistantMessage(content="Hi!"),
    ]
    state.agent = MagicMock()
    state.agent.llm = MagicMock()
    state.agent.agent_def.llm.get = MagicMock(return_value="gpt-4o")

    # Mock estimate_tokens to return low value
    guard.estimate_tokens = MagicMock(return_value=1000)

    result = await guard.check_and_compact(state)

    assert result is state
    state.agent.llm.chat.assert_not_called()


if __name__ == "__main__":
    test_context_guard_init()
    test_context_guard_default_threshold()
    test_truncate_large_tool_results()
    test_truncate_preserves_small_results()
    test_truncate_non_tool_messages()
    print("\nAll test_context_guard tests passed!")