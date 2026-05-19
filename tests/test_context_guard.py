from __future__ import annotations
"""ContextGuard 测试。"""
import pytest
from unittest.mock import AsyncMock, MagicMock
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


def test_offload_large_results():
    """测试大工具结果落盘（Tier 1 Offload）。"""
    import tempfile, os
    from src.SmallShrimp.core.context_guard import ContextGuard
    from src.SmallShrimp.core.message import HumanMessage, ToolMessage

    with tempfile.TemporaryDirectory() as tmpdir:
        guard = ContextGuard(context_window=500, offload_dir=tmpdir)

        large_content = "x" * 12000

        messages = [
            HumanMessage(content="Hello"),
            ToolMessage(content=large_content, tool_call_id="call1", name="test"),
        ]

        offloaded = guard._offload_large_results(messages)

        assert len(offloaded) == 2
        assert offloaded[0].content == "Hello"
        assert "To continue: read(path=" in offloaded[1].content
        assert "limit=" in offloaded[1].content
        assert "offset=" in offloaded[1].content
        assert offloaded[1].content.startswith(large_content[:5000])


def test_offload_preserves_small_results():
    """测试小结果不会落盘。"""
    import tempfile, os
    from src.SmallShrimp.core.context_guard import ContextGuard
    from src.SmallShrimp.core.message import ToolMessage

    with tempfile.TemporaryDirectory() as tmpdir:
        guard = ContextGuard(context_window=500, offload_dir=tmpdir)

        messages = [
            ToolMessage(content="Small result", tool_call_id="call1", name="test"),
        ]

        offloaded = guard._offload_large_results(messages)

        assert len(offloaded) == 1
        assert offloaded[0].content == "Small result"
        assert os.listdir(tmpdir) == []


def test_offload_non_tool_messages():
    """测试非工具消息不落盘。"""
    import tempfile
    from src.SmallShrimp.core.context_guard import ContextGuard
    from src.SmallShrimp.core.message import HumanMessage, AssistantMessage

    with tempfile.TemporaryDirectory() as tmpdir:
        guard = ContextGuard(context_window=500, offload_dir=tmpdir)

        messages = [
            HumanMessage(content="User message"),
            AssistantMessage(content="Assistant response"),
        ]

        offloaded = guard._offload_large_results(messages)

        assert len(offloaded) == 2
        assert offloaded[0].content == "User message"
        assert offloaded[1].content == "Assistant response"


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
    test_offload_large_results()
    test_offload_preserves_small_results()
    test_offload_non_tool_messages()
    print("\nAll test_context_guard tests passed!")
