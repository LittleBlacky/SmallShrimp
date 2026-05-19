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
    print("\nAll test_context_guard tests passed!")
