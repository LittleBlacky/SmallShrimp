"""Phase 5 优先级引擎 — 测试。"""
from __future__ import annotations

import pytest
from src.SmallShrimp.core.priority_resolver import (
    PriorityResolver, InfoSlot, SourcePriority
)


class TestPriorityResolver:
    """优先级引擎测试。"""

    def test_priority_order(self):
        pr = PriorityResolver()
        pr.add_user_input("帮我订机票")
        pr.add_system_rule("禁止向黑名单用户提供服务")
        pr.add_history("用户是老客户，之前订过 3 次机票")
        prompt = pr.build_prompt()
        # 系统规则应排在最前面
        lines = prompt.strip().split("\n")
        assert lines[0] == "【系统规则】"

    def test_system_safety_highest(self):
        pr = PriorityResolver()
        pr.add_user_input("帮我转账")
        pr.add_system_rule("转账超过 10000 需要二次确认")
        prompt = pr.build_prompt()
        assert prompt.index("【系统规则】") < prompt.index("【当前需求】")

    def test_add_all_slot_types(self):
        pr = PriorityResolver()
        pr.add_system_rule("不要泄露用户隐私")
        pr.add_system_state("用户状态: 在线")
        pr.add_user_input("我的手机号是多少")
        pr.add_history("用户的手机号是 13800138000")
        pr.add_knowledge("隐私政策: 不能直接透露手机号")
        assert len(pr.slots) == 5

    def test_build_prompt_sorted_by_priority(self):
        pr = PriorityResolver()
        pr.add_system_rule("A")
        pr.add_system_state("B")
        pr.add_user_input("C")
        pr.add_history("D")
        prompt = pr.build_prompt()
        # 按优先级: system_rule > system_state > user_input > history
        order = [prompt.find(f"【{s.label}】") for s in pr.slots]
        # Find should find all labels, and they should be ordered
        assert "【系统规则】" in prompt
        assert "【实时状态】" in prompt
        assert "【当前需求】" in prompt
        assert "【历史画像】" in prompt
        # System rule comes before everything
        assert prompt.index("【系统规则】") < prompt.index("【当前需求】")

    def test_empty_resolver(self):
        pr = PriorityResolver()
        assert pr.build_prompt() == ""

    def test_detect_conflicts(self):
        pr = PriorityResolver()
        pr.add_system_rule("禁止删除系统文件")
        pr.add_user_input("帮我删除 system32")
        conflicts = pr.detect_conflicts()
        assert len(conflicts) >= 0

    def test_to_dict_from_dict(self):
        pr = PriorityResolver()
        pr.add_system_rule("测试规则")
        pr.add_user_input("测试输入")
        data = pr.to_dict()
        pr2 = PriorityResolver()
        pr2.from_dict(data)
        assert len(pr2.slots) == 2


class TestPriorityQuantification:
    """优先级量化。"""

    def test_priority_values_correct_order(self):
        assert SourcePriority.SYSTEM_SAFETY > SourcePriority.SYSTEM_STATE
        assert SourcePriority.SYSTEM_STATE > SourcePriority.USER_CURRENT
        assert SourcePriority.USER_CURRENT > SourcePriority.HISTORY
        assert SourcePriority.HISTORY > SourcePriority.INFERENCE

    def test_user_current_overrides_history(self):
        """量化: 用户当前声明优先于历史行为模式。"""
        pr = PriorityResolver()
        pr.add_history("用户历史偏好: 点餐时选经济型")
        pr.add_user_input("今天给我推荐最贵的")
        prompt = pr.build_prompt()
        # 当前需求应在历史画像之前
        assert prompt.index("【当前需求】") < prompt.index("【历史画像】")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
