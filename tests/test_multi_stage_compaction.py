from __future__ import annotations
"""多阶段压缩测试。"""
from src.SmallShrimp.core.context_guard import ContextGuard
from src.SmallShrimp.core.message import HumanMessage, ToolMessage


def test_snip_duplicates_replaces_duplicate_reads():
    guard = ContextGuard(context_window=100000)
    messages = [
        ToolMessage(content="file_A", tool_call_id="id1", name="read"),
        ToolMessage(content="file_A", tool_call_id="id2", name="read"),
        ToolMessage(content="file_B", tool_call_id="id3", name="read"),
    ]
    result = guard._snip_duplicates(messages)
    assert "snipped" in result[0].content.lower()


def test_snip_duplicates_preserves_unique_reads():
    guard = ContextGuard(context_window=100000)
    messages = [
        ToolMessage(content="unique_A", tool_call_id="id1", name="read"),
        ToolMessage(content="unique_B", tool_call_id="id2", name="read"),
    ]
    result = guard._snip_duplicates(messages)
    assert "snipped" not in result[0].content.lower()


def test_microcompact_keeps_recent():
    guard = ContextGuard(context_window=100000)
    messages = [
        ToolMessage(content="old", tool_call_id="t1", name="test"),
        HumanMessage(content="recent"),
        ToolMessage(content="recent_tool", tool_call_id="t2", name="test"),
    ]
    result = guard._microcompact(messages)
    assert "recent_tool" in " ".join(m.content or "" for m in result)


def test_fill_ratio():
    guard = ContextGuard(context_window=200000)
    assert guard._fill_ratio(100000) == 0.5


def test_budget_truncate_read_hint():
    guard = ContextGuard(context_window=100000)
    msg = ToolMessage(content="A" * 12000, tool_call_id="c1", name="read")
    result = guard._budget_truncate([msg])
    assert "File truncated" in result[0].content
    assert "offset" in result[0].content.lower()
    assert "limit" in result[0].content.lower()


def test_budget_truncate_head_tail():
    guard = ContextGuard(context_window=100000)
    head = "HEAD_" + "A" * 4995
    tail = "TAIL_" + "Z" * 4995
    content = head + "M" * 2000 + tail
    msg = ToolMessage(content=content, tool_call_id="c1", name="grep")
    result = guard._budget_truncate([msg])
    assert "HEAD_" in result[0].content
    assert "TAIL_" in result[0].content
    assert "first and last" in result[0].content


if __name__ == "__main__":
    test_snip_duplicates_replaces_duplicate_reads()
    test_snip_duplicates_preserves_unique_reads()
    test_microcompact_keeps_recent()
    test_fill_ratio()
    test_budget_truncate_read_hint()
    test_budget_truncate_head_tail()
    print("All multi-stage compaction tests passed!")
