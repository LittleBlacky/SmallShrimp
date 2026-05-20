from __future__ import annotations
"""多阶段压缩测试。"""
import os
import tempfile
from src.SmallShrimp.core.context_guard import ContextGuard, PERSIST_THRESHOLD
from src.SmallShrimp.core.message import HumanMessage, ToolMessage


def test_snip_duplicates_replaces_old_results():
    """Snip: >60% context 且超过 KEEP_RECENT_RESULTS 时替换旧结果。"""
    guard = ContextGuard(context_window=200)
    padding = "x" * 500
    messages = [
        ToolMessage(content=f"result_1_{padding}", tool_call_id="id1", name="read"),
        ToolMessage(content=f"result_2_{padding}", tool_call_id="id2", name="read"),
        ToolMessage(content=f"result_3_{padding}", tool_call_id="id3", name="read"),
        ToolMessage(content=f"result_4_{padding}", tool_call_id="id4", name="grep"),
        ToolMessage(content=f"result_5_{padding}", tool_call_id="id5", name="glob"),
    ]
    result = guard._snip_duplicates(messages)
    assert "Content snipped" in result[0].content
    assert "Content snipped" in result[1].content


def test_snip_under_threshold_noop():
    """Snip: 低于 60% 不触发。"""
    guard = ContextGuard(context_window=100000)
    messages = [
        ToolMessage(content="result_1", tool_call_id="id1", name="read"),
        ToolMessage(content="result_2", tool_call_id="id2", name="read"),
    ]
    result = guard._snip_duplicates(messages)
    assert result[0].content == "result_1"


def test_microcompact_keeps_recent():
    """Microcompact: 保留最近 3 个，其余替换为 [Old result cleared]。"""
    guard = ContextGuard(context_window=1000)
    messages = [
        ToolMessage(content="old_1", tool_call_id="t1", name="test"),
        ToolMessage(content="old_2", tool_call_id="t2", name="test"),
        ToolMessage(content="old_3", tool_call_id="t3", name="test"),
        ToolMessage(content="old_4", tool_call_id="t4", name="test"),
        ToolMessage(content="recent", tool_call_id="t5", name="test"),
    ]
    result = guard._microcompact(messages)
    assert result[0].content == "[Old result cleared]"
    assert result[1].content == "[Old result cleared]"
    assert result[4].content == "recent"


def test_fill_ratio():
    guard = ContextGuard(context_window=200000)
    assert guard._fill_ratio(100000) == 0.5


def test_budget_truncate_head_tail():
    """Budget 截断：头尾保留，中间省略。"""
    guard = ContextGuard(context_window=10000)
    head = "HEAD_" + "A" * 5000
    tail = "TAIL_" + "Z" * 5000
    content = head + "M" * 20000 + tail
    msg = ToolMessage(content=content, tool_call_id="c1", name="read")
    result = guard._budget_truncate([msg])
    assert "budgeted" in result[0].content
    assert "HEAD_" in result[0].content
    assert "TAIL_" in result[0].content
    assert len(result[0].content) < len(content)


def test_persist_large_result():
    """>30KB 结果落盘 + 预览。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        guard = ContextGuard(context_window=100000, offload_dir=tmpdir)
        line = "line " + "x" * 100
        lines = [line for _ in range(500)]
        content = "\n".join(lines)
        assert len(content.encode("utf-8")) > PERSIST_THRESHOLD
        msg = ToolMessage(content=content, tool_call_id="c1", name="read")
        result = guard._persist_large_results([msg])
        assert "Result too large" in result[0].content
        assert "Preview (first 200 lines)" in result[0].content
        assert len(result[0].content) < len(content)
        assert len(os.listdir(tmpdir)) == 1


if __name__ == "__main__":
    test_snip_duplicates_replaces_old_results()
    test_snip_under_threshold_noop()
    test_microcompact_keeps_recent()
    test_fill_ratio()
    test_budget_truncate_head_tail()
    test_persist_large_result()
    print("All multi-stage compaction tests passed!")
