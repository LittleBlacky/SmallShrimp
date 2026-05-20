from __future__ import annotations
"""Tool guardrail 测试。"""
from src.SmallShrimp.core.tool_guardrails import (
    ToolGuardrailController,
    GuardrailConfig,
    append_guardrail_warning,
    GuardrailDecision,
)


def test_exact_failure_warns_after_2():
    ctrl = ToolGuardrailController(GuardrailConfig(exact_failure_warn_after=2))
    # 第 1 次失败 — 不警告
    d1 = ctrl.after_call("read", {"path": "a.txt"}, "Error: not found", failed=True)
    assert d1.action == "allow"
    # 第 2 次失败 — 警告
    d2 = ctrl.after_call("read", {"path": "a.txt"}, "Error: not found", failed=True)
    assert d2.action == "warn"
    assert d2.code == "exact_failure"
    assert "2 次" in d2.message


def test_same_tool_failure_warns_after_3():
    ctrl = ToolGuardrailController(GuardrailConfig(same_tool_failure_warn_after=3))
    # 同一工具，不同参数失败 3 次
    ctrl.after_call("grep", {"pattern": "x"}, "Error: timeout", failed=True)
    ctrl.after_call("grep", {"pattern": "y"}, "Error: timeout", failed=True)
    d3 = ctrl.after_call("grep", {"pattern": "z"}, "Error: timeout", failed=True)
    assert d3.action == "warn"
    assert d3.code == "same_tool_failure"
    assert "3 次" in d3.message


def test_no_progress_warns_after_2():
    ctrl = ToolGuardrailController(GuardrailConfig(no_progress_warn_after=2))
    # 只读工具返回相同结果 2 次
    ctrl.after_call("read", {"path": "a.txt"}, "same content", failed=False, is_read_only=True)
    d2 = ctrl.after_call("read", {"path": "a.txt"}, "same content", failed=False, is_read_only=True)
    assert d2.action == "warn"
    assert d2.code == "no_progress"
    assert "2 次" in d2.message


def test_no_progress_different_result_ok():
    ctrl = ToolGuardrailController(GuardrailConfig(no_progress_warn_after=2))
    ctrl.after_call("read", {"path": "a.txt"}, "content A", failed=False, is_read_only=True)
    d2 = ctrl.after_call("read", {"path": "a.txt"}, "content B", failed=False, is_read_only=True)
    assert d2.action == "allow"


def test_success_clears_failure_counters():
    ctrl = ToolGuardrailController(GuardrailConfig(exact_failure_warn_after=2))
    ctrl.after_call("read", {"path": "a.txt"}, "Error: fail", failed=True)
    # 成功后清零
    d2 = ctrl.after_call("read", {"path": "a.txt"}, "success", failed=False)
    assert d2.action == "allow"
    # 再次失败从头计数
    d3 = ctrl.after_call("read", {"path": "a.txt"}, "Error: fail", failed=True)
    assert d3.action == "allow"


def test_reset_clears_all():
    ctrl = ToolGuardrailController(GuardrailConfig(exact_failure_warn_after=2))
    ctrl.after_call("read", {"path": "a.txt"}, "Error: fail", failed=True)
    ctrl.after_call("read", {"path": "a.txt"}, "Error: fail", failed=True)
    assert ctrl._exact_failures
    ctrl.reset()
    assert not ctrl._exact_failures
    assert not ctrl._same_tool_failures
    assert not ctrl._no_progress


def test_append_warning():
    decision = GuardrailDecision(
        action="warn", code="exact_failure",
        message="read 已用相同参数失败 2 次。",
        tool_name="read", count=2,
    )
    result = append_guardrail_warning("file content", decision)
    assert "file content" in result
    assert "Tool Loop Warning" in result
    assert "exact_failure" in result


def test_append_no_warning_on_allow():
    decision = GuardrailDecision(action="allow")
    result = append_guardrail_warning("file content", decision)
    assert result == "file content"


if __name__ == "__main__":
    test_exact_failure_warns_after_2()
    test_same_tool_failure_warns_after_3()
    test_no_progress_warns_after_2()
    test_no_progress_different_result_ok()
    test_success_clears_failure_counters()
    test_reset_clears_all()
    test_append_warning()
    test_append_no_warning_on_allow()
    print("All tool guardrail tests passed!")
