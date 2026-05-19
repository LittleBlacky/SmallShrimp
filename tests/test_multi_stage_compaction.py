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


def test_truncate_glob():
    guard = ContextGuard(context_window=100000)
    files = "\n".join(f"src/module_{i}/very_long_file_name_for_testing_purposes.py" for i in range(500))
    msg = ToolMessage(content=files, tool_call_id="c1", name="glob")
    result = guard._budget_truncate([msg])
    assert "files omitted" in result[0].content


def test_truncate_grep():
    guard = ContextGuard(context_window=100000)
    padding = "x" * 80
    matches = "\n".join(f"file_{i}.py: line_{i}: found 'pattern_{padding}'" for i in range(500))
    msg = ToolMessage(content=matches, tool_call_id="c1", name="grep")
    result = guard._budget_truncate([msg])
    assert "matches omitted" in result[0].content


def test_truncate_websearch():
    guard = ContextGuard(context_window=100000)
    entries = [f"{i}. **Title {i} {'x' * 200}**\n   http://example.com/{i}\n   {'Snippet ' * 50}" for i in range(50)]
    content = "\n\n".join(entries)
    msg = ToolMessage(content=content, tool_call_id="c1", name="websearch")
    result = guard._budget_truncate([msg])
    assert "results omitted" in result[0].content


def test_truncate_read_range():
    guard = ContextGuard(context_window=100000)
    padding = "x" * 100
    lines = [f"line {i} {padding}" for i in range(200)]
    content = f"[Lines 0-199 of 200]\n" + "\n".join(lines)
    msg = ToolMessage(content=content, tool_call_id="c1", name="read")
    result = guard._budget_truncate([msg])
    assert "missing lines" in result[0].content.lower()


def test_truncate_head_tail():
    guard = ContextGuard(context_window=100000)
    head = "HEAD_" + "A" * 4995
    tail = "TAIL_" + "Z" * 4995
    content = head + "M" * 2000 + tail
    msg = ToolMessage(content=content, tool_call_id="c1", name="grep")
    result = guard._budget_truncate([msg])


if __name__ == "__main__":
    test_snip_duplicates_replaces_duplicate_reads()
    test_snip_duplicates_preserves_unique_reads()
    test_microcompact_keeps_recent()
    test_fill_ratio()
    test_truncate_glob()
    test_truncate_grep()
    test_truncate_websearch()
    test_truncate_read_range()
    test_truncate_head_tail()
    print("All multi-stage compaction tests passed!")
