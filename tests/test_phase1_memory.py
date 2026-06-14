"""Phase 1 记忆层改进 - 量化实验。

实验 1: COMPACT_PROMPT 约束保留率对比
实验 2: constraints 层读写 + 注入验证
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import pytest

from src.SmallShrimp.core.memory.builtin.common import VALID_MEMORY_LAYERS
from src.SmallShrimp.core.memory.builtin.file_store import MarkdownStore
from src.SmallShrimp.core.memory.builtin.provider import BuiltinProvider


# ═══════════════════════════════════════════════════════════
# 实验 1: COMPACT_PROMPT 约束保留率
# ═══════════════════════════════════════════════════════════

class TestCompactPromptConstraintPreservation:
    """量化 COMPACT_PROMPT 对约束的保留能力。"""

    # 模拟含约束的对话
    CONSTRAINED_CONVERSATION = """[HumanMessage]: 帮我推荐餐厅，我预算不超过500元，不要辣的
[AssistantMessage]: 好的，预算500以内，不吃辣，我帮您搜索...
[ToolMessage]: 搜索结果: 1. 粤菜馆 人均200 2. 日料 人均350 3. 川菜馆 人均150
[HumanMessage]: 川菜馆不行，我对花生过敏，千万别推荐含花生的
[AssistantMessage]: 明白，排除川菜馆，排除含花生的菜品。您的约束: 预算≤500, 不吃辣, 不含花生
[HumanMessage]: 谢谢
[AssistantMessage]: 不客气！
[HumanMessage]: 对了，必须能预约今晚的位置
[AssistantMessage]: 好的，加上今晚可预约的条件。"""

    def test_prompt_contains_selective_instructions(self):
        """验证 COMPACT_PROMPT 包含分级压缩指令。"""
        from src.SmallShrimp.core.context_guard import COMPACT_PROMPT

        # 必须包含的关键词
        assert "Verbatim" in COMPACT_PROMPT or "原文" in COMPACT_PROMPT
        assert "Negative constraints" in COMPACT_PROMPT or "否定" in COMPACT_PROMPT
        assert "Numeric constraints" in COMPACT_PROMPT or "数字" in COMPACT_PROMPT
        assert "Summarize" in COMPACT_PROMPT or "压缩" in COMPACT_PROMPT
        assert "Drop" in COMPACT_PROMPT or "丢弃" in COMPACT_PROMPT
        # 强制保留检查
        assert "do NOT paraphrase" in COMPACT_PROMPT or "不压缩" in COMPACT_PROMPT
        assert "Hard Constraints" in COMPACT_PROMPT

    def test_prompt_explicitly_requires_verbatim_constraints(self):
        """验证 prompt 显式要求约束原文保留。"""
        from src.SmallShrimp.core.context_guard import COMPACT_PROMPT

        # 检查约束原文保留的指令
        assert "Verbatim" in COMPACT_PROMPT
        assert "copy-paste" in COMPACT_PROMPT
        assert "EXACT original text" in COMPACT_PROMPT
        assert "MUST Preserve" in COMPACT_PROMPT

    def test_prompt_separates_summarize_and_drop(self):
        """验证 prompt 区分了可摘要和可丢弃的内容类型。"""
        from src.SmallShrimp.core.context_guard import COMPACT_PROMPT

        assert "CAN Summarize" in COMPACT_PROMPT
        assert "CAN Drop" in COMPACT_PROMPT
        assert "Pleasantries" in COMPACT_PROMPT
        assert "Discussion flow" in COMPACT_PROMPT

    def test_prompt_has_structured_output_format(self):
        """验证 prompt 要求结构化输出。"""
        from src.SmallShrimp.core.context_guard import COMPACT_PROMPT

        assert "## 硬性约束" in COMPACT_PROMPT
        assert "## 关键决策" in COMPACT_PROMPT
        assert "## 对话摘要" in COMPACT_PROMPT
        assert "## 待解决" in COMPACT_PROMPT

    def test_compact_prompt_length_comparison(self):
        """量化：新旧 prompt 长度对比。"""
        OLD_PROMPT = """Your task is to create a detailed summary of the conversation so far, capturing the user's requests, your actions, and any important context needed to continue without losing information.

Your summary should include:
1. Primary Request and Intent
2. Key Facts and User Preferences
3. User Messages (ALL user messages)
4. Errors and Corrections
5. Current Work and Pending Tasks

Here is the conversation to summarize:

{conversation}

Please provide your summary following this structure."""

        from src.SmallShrimp.core.context_guard import COMPACT_PROMPT

        old_chars = len(OLD_PROMPT)
        new_chars = len(COMPACT_PROMPT)

        print(f"\n  旧 COMPACT_PROMPT: {old_chars} chars")
        print(f"  新 COMPACT_PROMPT: {new_chars} chars")
        print(f"  增加: {new_chars - old_chars} chars ({(new_chars/old_chars - 1)*100:.0f}%)")

        # 新 prompt 更长（更详细的指令），但仍在合理范围
        assert new_chars > old_chars, "新 prompt 应该有更多指令"
        assert new_chars < 3000, f"新 prompt 不应过长: {new_chars} chars"


# ── 共享 fixture ──────────────────────────────────────

@pytest.fixture
def provider():
    """创建临时 BuiltinProvider。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        memory_dir = Path(tmpdir) / "memories"
        p = BuiltinProvider(memory_dir)
        yield p
        p.close()


# ═══════════════════════════════════════════════════════════
# 实验 2: constraints 层功能验证
# ═══════════════════════════════════════════════════════════

class TestConstraintsLayer:
    """验证 constraints 层的读写、注入和工具。"""

    def test_constraints_in_valid_layers(self):
        """验证 'constraints' 在 VALID_MEMORY_LAYERS 中。"""
        assert "constraints" in VALID_MEMORY_LAYERS

    def test_constraints_layer_declared(self, provider):
        """验证 constraints Layer 已声明。"""
        layers = provider.layers
        assert "constraints" in layers, f"layers keys: {list(layers.keys())}"
        layer = layers["constraints"]
        assert layer.name == "constraints"
        assert layer.searchable is True
        assert layer.inject == "session"

    def test_store_and_retrieve_constraint(self, provider):
        """验证写入和检索 constraint。"""
        provider.initialize("test_session")
        
        record = provider.store("constraints", "预算不超过500元")
        assert record["layer"] == "constraints"
        assert "预算不超过500元" in record["content"]

        # 用 list_all 验证持久化
        all_constraints = provider.list_all(layer="constraints")
        assert len(all_constraints) > 0
        assert any("预算不超过500元" in r["content"] for r in all_constraints)

    def test_constraints_injected_in_prompt_blocks(self, provider):
        """验证 constraints 出现在 get_prompt_blocks 中。"""
        provider.initialize("test_session")
        
        # 写入 constraint
        provider.store("constraints", "不含花生")
        
        # 刷新快照以包含新写入的 constraint
        provider.refresh_snapshot()
        
        blocks = provider.get_prompt_blocks()
        
        # 应该有 constraints block
        constraint_blocks = [b for b in blocks if "constraint" in b.name.lower() or "约束" in b.name]
        assert len(constraint_blocks) > 0, f"未找到 constraints block，blocks: {[b.name for b in blocks]}"

    def test_constraints_block_before_profile(self, provider):
        """验证 constraints block 在 profile block 之前（优先级更高）。"""
        provider.initialize("test_session")
        # 同时写入 profile 和 constraint，确保两个 block 都出现
        provider.store("constraints", "必须今晚可预约")
        provider.store("profile", "用户喜欢日料")
        provider.refresh_snapshot()
        
        blocks = provider.get_prompt_blocks()
        names = [b.name for b in blocks]
        
        assert len(blocks) >= 2, f"应至少有两个 block: {names}"
        # constraints 应该在前（block 名为 "Hard Constraints" / "User Profile"）
        constraint_idx = next(i for i, n in enumerate(names) if "Hard Constraints" in n)
        profile_idx = next(i for i, n in enumerate(names) if "User Profile" in n)
        assert constraint_idx < profile_idx, f"constraints 应在 profile 之前: {names}"

    def test_remember_constraint_tool_exists(self, provider):
        """验证 remember_constraint 工具已注册。"""
        tools = provider.get_tools()
        tool_names = [t.name if hasattr(t, 'name') else str(t) for t in tools]
        assert any("constraint" in name.lower() for name in tool_names), \
            f"未找到 constraint 工具: {tool_names}"

    def test_multiple_constraints(self, provider):
        """验证多条 constraint 的存储和检索。"""
        provider.initialize("test_session")
        
        constraints = [
            "预算不超过500元",
            "不含花生",
            "必须今晚可预约",
            "不能推荐川菜",
        ]
        for c in constraints:
            provider.store("constraints", c)
        
        provider.refresh_snapshot()
        
        # 列出所有
        all_constraints = provider.list_all(layer="constraints")
        assert len(all_constraints) >= len(constraints)

    def test_constraints_snapshot_persistence(self, provider):
        """验证 constraints 快照在 initialize 间的持久性。"""
        provider.initialize("session_1")
        provider.store("constraints", "预算≤500")
        
        # 重新初始化
        provider.initialize("session_2")
        
        all_c = provider._stores["constraints"].list_all()
        assert len(all_c) >= 1
        assert any("预算≤500" in r["content"] for r in all_c)


# ═══════════════════════════════════════════════════════════
# 实验 3: Constraints 层不参与压缩的架构验证
# ═══════════════════════════════════════════════════════════

class TestConstraintsExcludedFromCompaction:
    """验证 constraints 层的架构隔离 —— 不参与 Autocompact 压缩流程。"""

    def test_constraints_not_in_prefetch_layers(self):
        """验证 constraints 不在 prefetch 层中（走注入而非检索）。"""
        from src.SmallShrimp.core.memory.builtin.provider import _PREFETCH_LAYERS
        assert "constraints" not in _PREFETCH_LAYERS

    def test_constraints_has_session_inject(self, provider):
        """验证 constraints 声明为 session 级注入。"""
        layers = provider.layers
        assert layers["constraints"].inject == "session"

    def test_constraints_separate_from_search_default(self, provider):
        """验证跨层搜索时 constraints 不混杂到其他层结果中。"""
        provider.initialize("test")
        provider.store("constraints", "不含花生")
        provider.store("facts", "用户喜欢日料")
        
        # 在 facts 层列出不应返回 constraints
        facts_records = provider.list_all(layer="facts")
        # constraints 不应泄漏到 facts
        assert not any(
            r.get("layer") == "constraints"
            for r in facts_records
        ), "constraints 不应泄漏到 facts 结果"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
