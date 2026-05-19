from __future__ import annotations
"""ContextGuard 测试。"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.SmallShrimp.core.context_guard import ContextGuard, MEMORY_LINE_RE


def test_memory_line_regex_no_tags():
    """MEMORY 行可以不带 tags。"""
    match = MEMORY_LINE_RE.match("MEMORY: 用户喜欢使用 dark mode")
    assert match is not None
    assert match.group(1) == "用户喜欢使用 dark mode"
    assert match.group(2) is None


def test_memory_line_regex_with_tags():
    """MEMORY 行可以带 tags。"""
    match = MEMORY_LINE_RE.match("MEMORY: 用户偏好 Python [tags: preference, auto]")
    assert match is not None
    assert match.group(1) == "用户偏好 Python"
    assert match.group(2) == "preference, auto"


def test_memory_line_regex_case_insensitive():
    """MEMORY 行匹配不区分大小写。"""
    match = MEMORY_LINE_RE.match("memory: test content [tags: fact]")
    assert match is not None
    assert match.group(1) == "test content"


def test_memory_line_regex_multiline():
    """MEMORY 行支持多行匹配。"""
    text = """Summary line 1
    MEMORY: 用户用的是 VSCode [tags: fact, preference]
    Some other content
    MEMORY: 项目名叫 SmallShrimp [tags: fact]"""
    matches = list(MEMORY_LINE_RE.finditer(text))
    assert len(matches) == 2
    assert matches[0].group(1) == "用户用的是 VSCode"
    assert "fact" in matches[0].group(2)
    assert matches[1].group(1) == "项目名叫 SmallShrimp"


def test_memory_line_regex_no_match():
    """普通文本不匹配 MEMORY 正则。"""
    assert MEMORY_LINE_RE.match("Just some text") is None
    assert MEMORY_LINE_RE.match("MEMORY without colon") is None


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
    test_memory_line_regex_no_tags()
    test_memory_line_regex_with_tags()
    test_memory_line_regex_case_insensitive()
    test_memory_line_regex_multiline()
    test_memory_line_regex_no_match()
    test_context_guard_init()
    test_context_guard_default_threshold()
    test_truncate_large_tool_results()
    test_truncate_preserves_small_results()
    test_truncate_non_tool_messages()
    print("\nAll test_context_guard tests passed!")