from __future__ import annotations
"""ContextGuard 测试。"""
import pytest
from unittest.mock import MagicMock
from src.SmallShrimp.core.context_guard import ContextGuard


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


def test_budget_truncate_large_results():
    """测试 Budget 截断大工具结果（Tier 1）。"""
    from src.SmallShrimp.core.message import HumanMessage, ToolMessage

    guard = ContextGuard(context_window=10000)

    large_content = "x" * 50000
    messages = [
        HumanMessage(content="Hello"),
        ToolMessage(content=large_content, tool_call_id="call1", name="test"),
    ]

    truncated = guard._budget_truncate(messages)
    assert len(truncated) == 2
    assert truncated[0].content == "Hello"
    assert "budgeted" in truncated[1].content
    assert len(truncated[1].content) < len(large_content)


def test_snip_under_threshold_noop():
    """Snip: 低于 60% 不触发。"""
    from src.SmallShrimp.core.message import ToolMessage

    guard = ContextGuard(context_window=100000)
    messages = [ToolMessage(content="small", tool_call_id="c1", name="read")]
    result = guard._snip_duplicates(messages)
    assert result[0].content == "small"


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
    test_budget_truncate_large_results()
    test_snip_under_threshold_noop()
    print("\nAll test_context_guard tests passed!")
