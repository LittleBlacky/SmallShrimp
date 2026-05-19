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


if __name__ == "__main__":
    test_snip_duplicates_replaces_duplicate_reads()
    test_snip_duplicates_preserves_unique_reads()
    test_microcompact_keeps_recent()
    test_fill_ratio()
    print("All multi-stage compaction tests passed!")
