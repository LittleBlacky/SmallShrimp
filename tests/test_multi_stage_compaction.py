from __future__ import annotations
"""多阶段压缩测试。"""
import os
import tempfile
from src.SmallShrimp.core.context_guard import ContextGuard, OFFLOAD_SIZE_THRESHOLD
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


def test_offload_glob_writes_file():
    """glob 大结果落盘，消息中保留摘要 + read 路径。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        guard = ContextGuard(context_window=500, offload_dir=tmpdir)
        files = "\n".join(f"src/module_{i}/very_long_file_name_for_testing.py" for i in range(250))
        # 确保超过 OFFLOAD_SIZE_THRESHOLD
        assert len(files) > OFFLOAD_SIZE_THRESHOLD
        msg = ToolMessage(content=files, tool_call_id="c1", name="glob")
        result = guard._offload_large_results([msg])
        content = result[0].content
        assert "[Offloaded:" in content
        assert "Use read(path=" in content
        # 确认落盘文件存在且内容完整
        offloaded_files = os.listdir(tmpdir)
        assert len(offloaded_files) == 1
        with open(os.path.join(tmpdir, offloaded_files[0]), encoding="utf-8") as f:
            assert f.read() == files


def test_offload_grep_writes_file():
    """grep 大结果落盘。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        guard = ContextGuard(context_window=500, offload_dir=tmpdir)
        padding = "x" * 80
        matches = "\n".join(f"file_{i}.py: line_{i}: found 'pattern_{padding}'" for i in range(500))
        assert len(matches) > OFFLOAD_SIZE_THRESHOLD
        msg = ToolMessage(content=matches, tool_call_id="c1", name="grep")
        result = guard._offload_large_results([msg])
        content = result[0].content
        assert "[Offloaded:" in content
        assert "Use read(path=" in content
        assert "more matches" in content
        # 落盘文件完整
        offloaded_files = os.listdir(tmpdir)
        assert len(offloaded_files) == 1


def test_offload_websearch_writes_file():
    """websearch 大结果落盘。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        guard = ContextGuard(context_window=500, offload_dir=tmpdir)
        entries = [f"{i}. **Title {i} {'x' * 200}**\n   http://example.com/{i}\n   {'Snippet ' * 50}" for i in range(30)]
        content = "\n\n".join(entries)
        assert len(content) > OFFLOAD_SIZE_THRESHOLD
        msg = ToolMessage(content=content, tool_call_id="c1", name="websearch")
        result = guard._offload_large_results([msg])
        assert "[Offloaded:" in result[0].content
        assert "Use read(path=" in result[0].content


def test_offload_read_writes_file():
    """read 大结果落盘。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        guard = ContextGuard(context_window=500, offload_dir=tmpdir)
        padding = "x" * 100
        lines = [f"line {i} {padding}" for i in range(200)]
        content = f"[Lines 0-199 of 200]\n" + "\n".join(lines)
        assert len(content) > OFFLOAD_SIZE_THRESHOLD
        msg = ToolMessage(content=content, tool_call_id="c1", name="read")
        result = guard._offload_large_results([msg])
        assert "[Offloaded:" in result[0].content
        assert "Use read(path=" in result[0].content


def test_offload_small_untouched():
    """小结果不落盘。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        guard = ContextGuard(context_window=500, offload_dir=tmpdir)
        msg = ToolMessage(content="small result", tool_call_id="c1", name="read")
        result = guard._offload_large_results([msg])
        assert result[0].content == "small result"
        assert os.listdir(tmpdir) == []


if __name__ == "__main__":
    test_snip_duplicates_replaces_duplicate_reads()
    test_snip_duplicates_preserves_unique_reads()
    test_microcompact_keeps_recent()
    test_fill_ratio()
    test_offload_glob_writes_file()
    test_offload_grep_writes_file()
    test_offload_websearch_writes_file()
    test_offload_read_writes_file()
    test_offload_small_untouched()
    print("All multi-stage compaction tests passed!")
