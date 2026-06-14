"""Phase 3 To-do List + 工具态记忆 — 测试与量化。"""
from __future__ import annotations

import pytest
from src.SmallShrimp.core.todo_tracker import TodoTracker, TaskItem, TaskStatus
from src.SmallShrimp.core.tool_state import ToolStateMemory


# ═══════════════════════════════════════════════════════════
# TodoTracker 测试
# ═══════════════════════════════════════════════════════════

class TestTodoTracker:
    """To-do List 锚点机制测试。"""

    def test_create_task(self):
        tdl = TodoTracker()
        t = tdl.create_task("分析用户需求")
        assert t.title == "分析用户需求"
        assert t.status == TaskStatus.PENDING
        assert len(tdl.tasks) == 1

    def test_update_status(self):
        tdl = TodoTracker()
        t = tdl.create_task("查询数据库")
        assert tdl.update_status(t.id, TaskStatus.IN_PROGRESS) is True
        assert tdl.tasks[0].status == TaskStatus.IN_PROGRESS

    def test_update_with_conclusion(self):
        tdl = TodoTracker()
        t = tdl.create_task("生成推荐")
        tdl.update_status(t.id, TaskStatus.COMPLETED, conclusion="推荐了 3 个商品")
        assert tdl.tasks[0].conclusion == "推荐了 3 个商品"

    def test_remove_task(self):
        tdl = TodoTracker()
        t = tdl.create_task("删除我")
        assert tdl.remove(t.id) is True
        assert len(tdl.tasks) == 0

    def test_find_by_title(self):
        tdl = TodoTracker()
        tdl.create_task("查询数据库")
        tdl.create_task("发送邮件通知")
        results = tdl.find("邮件")
        assert len(results) == 1
        assert results[0].title == "发送邮件通知"

    def test_build_prompt_block_empty(self):
        tdl = TodoTracker()
        assert tdl.build_prompt_block() == ""

    def test_build_prompt_block_with_tasks(self):
        tdl = TodoTracker()
        t1 = tdl.create_task("分析需求")
        t2 = tdl.create_task("写代码")
        tdl.create_task("测试")
        tdl.update_status(t1.id, TaskStatus.COMPLETED, "已分析完毕")
        tdl.update_status(t2.id, TaskStatus.IN_PROGRESS)
        block = tdl.build_prompt_block()
        assert "✅" in block or "✔️" in block  # 已完成
        assert "🔄" in block or "进行中" in block  # 进行中
        assert "⏳" in block  # 待处理

    def test_to_dict_from_dict_roundtrip(self):
        tdl = TodoTracker()
        tdl.create_task("A")
        tdl.create_task("B")
        data = tdl.to_dict()
        tdl2 = TodoTracker()
        tdl2.from_dict(data)
        assert len(tdl2.tasks) == 2
        assert tdl2.tasks[0].title == "A"


class TestTodoQuantification:
    """To-do List 量化指标。"""

    def test_completed_task_folded(self):
        """已完成+有结论的任务应折叠为一行。"""
        tdl = TodoTracker()
        t = tdl.create_task("查询数据库，获取用户最近订单，统计金额")
        tdl.update_status(t.id, TaskStatus.COMPLETED, "查到 5 笔订单，共 3000 元")
        block = tdl.build_prompt_block()
        # 结论应出现在 prompt 中
        assert "查到 5 笔订单" in block

    def test_in_progress_task_not_folded(self):
        """进行中的任务应保留完整标题。"""
        tdl = TodoTracker()
        t = tdl.create_task("分析用户行为数据")
        tdl.update_status(t.id, TaskStatus.IN_PROGRESS)
        block = tdl.build_prompt_block()
        assert "分析用户行为数据" in block

    def test_status_transition_count(self):
        """验证状态转换完整性。"""
        tdl = TodoTracker()
        t = tdl.create_task("测试")

        # pending → in_progress → completed
        tdl.update_status(t.id, TaskStatus.IN_PROGRESS)
        assert tdl.tasks[0].status == TaskStatus.IN_PROGRESS

        tdl.update_status(t.id, TaskStatus.COMPLETED)
        assert tdl.tasks[0].status == TaskStatus.COMPLETED

        # blocked
        t = tdl.create_task("阻塞任务")
        tdl.update_status(t.id, TaskStatus.BLOCKED)
        assert tdl.tasks[1].status == TaskStatus.BLOCKED

    def test_multiple_tasks_budget(self):
        """量化: N 个任务时 prompt block 不超限。"""
        tdl = TodoTracker()
        for i in range(10):
            tdl.create_task(f"任务{i}")
        block = tdl.build_prompt_block()
        assert len(block) < 500, f"prompt block 过长: {len(block)} chars"


# ═══════════════════════════════════════════════════════════
# ToolStateMemory 测试
# ═══════════════════════════════════════════════════════════

class TestToolStateMemory:
    """工具态记忆测试。"""

    def test_record_call(self):
        tsm = ToolStateMemory()
        r = tsm.record_call("read", {"path": "file.txt"}, "200 lines")
        assert r.tool_name == "read"
        assert r.success is True

    def test_find_recent_same_params(self):
        tsm = ToolStateMemory()
        tsm.record_call("grep", {"pattern": "TODO"}, "3 matches")
        result = tsm.find_recent("grep", {"pattern": "TODO"})
        assert result is not None
        assert result.result_summary == "3 matches"

    def test_find_recent_different_params(self):
        tsm = ToolStateMemory()
        tsm.record_call("grep", {"pattern": "TODO"}, "3 matches")
        result = tsm.find_recent("grep", {"pattern": "FIXME"})
        assert result is None

    def test_should_skip_successful(self):
        tsm = ToolStateMemory()
        tsm.record_call("read", {"path": "a.py"}, "content...", success=True)
        skip, reason = tsm.should_skip("read", {"path": "a.py"})
        assert skip is True
        assert "成功" in reason

    def test_should_skip_failed(self):
        tsm = ToolStateMemory()
        tsm.record_call("write", {"path": "/etc/passwd"}, "", success=False, error_message="permission denied")
        skip, reason = tsm.should_skip("write", {"path": "/etc/passwd"})
        assert skip is True
        assert "失败" in reason

    def test_should_not_skip_new_call(self):
        tsm = ToolStateMemory()
        skip, reason = tsm.should_skip("read", {"path": "new.txt"})
        assert skip is False

    def test_stats(self):
        tsm = ToolStateMemory()
        tsm.record_call("read", {"path": "a"}, "ok", success=True)
        tsm.record_call("read", {"path": "b"}, "ok", success=True)
        tsm.record_call("write", {"path": "c"}, "", success=False, error_message="err")
        s = tsm.stats()
        assert s["read"]["success"] == 2
        assert s["read"]["calls"] == 2
        assert s["write"]["failures"] == 1
        assert s["write"]["success_rate"] == 0.0

    def test_build_context_block(self):
        tsm = ToolStateMemory()
        tsm.record_call("read", {"path": "config.py"}, "100 lines", success=True)
        block = tsm.build_context_block()
        assert "✅" in block or "read" in block


class TestToolStateQuantification:
    """工具态量化指标。"""

    def test_dedup_prevents_duplicate_calls(self):
        """量化: 相同参数在 cache TTL 内应被跳过。"""
        tsm = ToolStateMemory()
        tsm.record_call("search", {"q": "test"}, "5 results", success=True)
        check = tsm.should_skip("search", {"q": "test"})
        assert check[0] is True

    def test_different_params_not_blocked(self):
        """量化: 不同参数不被去重影响。"""
        tsm = ToolStateMemory()
        tsm.record_call("search", {"q": "test"}, "5 results", success=True)
        tsm.record_call("search", {"q": "other"}, "10 results", success=True)
        check = tsm.should_skip("search", {"q": "other"})
        assert check[0] is True  # same params → skip
        check2 = tsm.should_skip("search", {"q": "new_one"})
        assert check2[0] is False  # different → not skip

    def test_failure_tracking(self):
        """量化: 失败被追踪且可回溯。"""
        tsm = ToolStateMemory()
        tsm.record_call("write", {"path": "x"}, "", success=False, error_message="disk full")
        tsm.record_call("write", {"path": "x"}, "", success=False, error_message="disk full")
        failures = tsm.recent_failures(5)
        assert len(failures) == 2

    def test_to_dict_from_dict_roundtrip(self):
        tsm = ToolStateMemory()
        tsm.record_call("read", {"path": "a"}, "ok")
        data = tsm.to_dict()
        tsm2 = ToolStateMemory()
        tsm2.from_dict(data)
        assert len(tsm2.records) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
