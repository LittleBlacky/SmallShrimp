"""置信度管线测试。

覆盖:
    - SignalDetector 各信号识别
    - ConfidenceGate 裁决逻辑
    - StagingArea 暂存与提升
    - MemoryManager.store() 整合
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from src.SmallShrimp.core.memory.confidence import (
    SignalDetector,
    ConfidenceGate,
    StagingArea,
    RoutingDecision,
    THRESHOLD_DIRECT,
    THRESHOLD_STAGING,
    PROMOTION_COUNT,
)
from src.SmallShrimp.core.memory import MemoryManager


# ═══════════════════════════════════════════════════════════
# SignalDetector 测试
# ═══════════════════════════════════════════════════════════

class TestSignalDetector:

    def test_detect_correction(self):
        """用户纠正信号。"""
        signals = SignalDetector.detect_all(
            "任何内容", source="user",
            user_msg="不对，你理解错了"
        )
        assert signals.get("correction") == 0.9

    def test_detect_failure_learner(self):
        """工具失败信号（failure_learner 来源）。"""
        signals = SignalDetector.detect_all("工具调用失败", source="failure_learner")
        assert signals.get("failure") == 0.8

    def test_detect_failure_by_flag(self):
        """工具失败信号（has_failure 标记）。"""
        signals = SignalDetector.detect_all("出错了", source="auto", has_failure=True)
        assert signals.get("failure") == 0.8

    def test_detect_repetition_exact_match(self):
        """重复信号 — 精确子串匹配。"""
        existing = [{"content": "用户喜欢 Python 编程"}]
        signals = SignalDetector.detect_all(
            "用户喜欢 Python 编程", existing_records=existing, source="auto"
        )
        assert signals.get("repetition") == 0.7

    def test_detect_repetition_fuzzy_match(self):
        """重复信号 — 模糊匹配 > 0.8。"""
        existing = [{"content": "用户喜欢用 Python 写代码"}]
        signals = SignalDetector.detect_all(
            "用户喜欢 Python 编程", existing_records=existing, source="auto"
        )
        assert signals.get("repetition") == 0.7

    def test_detect_keyword_trigger(self):
        """关键词触发信号。"""
        cases = ["我叫小明", "记住这个路径", "我是后端开发", "不要删除这个文件"]
        for content in cases:
            signals = SignalDetector.detect_all(content, source="auto")
            assert signals.get("keyword") == 0.5, f"Failed for: {content}"

    def test_detect_llm_call(self):
        """LLM 自觉调用信号。"""
        sources = ["remember_tool", "llm_tool", "llm"]
        for source in sources:
            signals = SignalDetector.detect_all("任何内容", source=source)
            assert signals.get("llm") == 0.3, f"Failed for source: {source}"

    def test_signal_priority_max(self):
        """多个信号时取最高分。"""
        signals = SignalDetector.detect_all(
            "不对，我叫小明",
            source="remember_tool",
            user_msg="不对，不是这样",
        )
        # correction=0.9, keyword=0.5, llm=0.3
        assert max(signals.values()) == 0.9

    def test_no_signal(self):
        """无信号时返回空字典。"""
        signals = SignalDetector.detect_all("今天天气不错", source="auto")
        assert signals == {}

    def test_empty_content(self):
        """空内容不触发任何信号（即使有 source 标记）。"""
        signals = SignalDetector.detect_all("", source="remember_tool")
        assert signals == {}

    def test_empty_content_no_source(self):
        """空内容 + 无 source 也是空。"""
        signals = SignalDetector.detect_all("  ", source="auto")
        assert signals == {}


# ═══════════════════════════════════════════════════════════
# ConfidenceGate 测试
# ═══════════════════════════════════════════════════════════

class TestConfidenceGate:

    def test_write_decision(self):
        """高置信度 → write。"""
        gate = ConfidenceGate()
        decision = gate.judge("profile", "用户信息", {"correction": 0.9})
        assert decision.action == "write"
        assert decision.confidence == 0.9
        assert decision.target_layer == "profile"

    def test_stage_decision(self):
        """中等置信度 → stage。"""
        gate = ConfidenceGate()
        decision = gate.judge("facts", "记住某事", {"keyword": 0.5})
        assert decision.action == "stage"
        assert decision.confidence == 0.5

    def test_discard_decision(self):
        """低置信度 → discard。"""
        gate = ConfidenceGate()
        decision = gate.judge("facts", "随便一说", {"llm": 0.3})
        assert decision.action == "discard"
        assert decision.confidence == 0.3

    def test_discard_no_signals(self):
        """空信号 → discard。"""
        gate = ConfidenceGate()
        decision = gate.judge("facts", "今天天气不错", {})
        assert decision.action == "discard"
        assert decision.confidence == 0.0

    def test_boundary_write(self):
        """边界值：刚好在写入阈值。"""
        gate = ConfidenceGate()
        decision = gate.judge("profile", "内容", {"test": THRESHOLD_DIRECT})
        assert decision.action == "write"

    def test_boundary_stage(self):
        """边界值：刚好在暂存阈值。"""
        gate = ConfidenceGate()
        decision = gate.judge("facts", "内容", {"test": THRESHOLD_STAGING})
        assert decision.action == "stage"

    def test_boundary_discard(self):
        """边界值：刚好低于暂存阈值。"""
        gate = ConfidenceGate()
        decision = gate.judge("facts", "内容", {"test": THRESHOLD_STAGING - 0.01})
        assert decision.action == "discard"


# ═══════════════════════════════════════════════════════════
# StagingArea 测试
# ═══════════════════════════════════════════════════════════

class TestStagingArea:

    def test_stage_first_time(self):
        """首次暂存。"""
        staging = StagingArea(":memory:")
        result = staging.stage("测试内容", "facts", 0.5)
        assert result["action"] == "staged"
        assert result["count"] == 1
        assert staging.count() == 1
        staging.close()

    def test_stage_bump(self):
        """同内容第二次暂存 → bumped（因为 promotion_count 为 2 时已提升，第三次才 bump）。
        注意 PROMOTION_COUNT=2，所以第二次出现时立即提升。
        """
        promoted = []
        def cb(h, c, l, **kw):
            promoted.append(c)

        staging = StagingArea(":memory:", promote_callback=cb)
        staging.stage("测试内容", "facts", 0.5)
        r1 = staging.stage("测试内容", "facts", 0.5)
        # 第二次出现 → 提升（PROMOTION_COUNT=2）
        assert r1["action"] == "promoted"
        assert len(promoted) == 1

        # 第三次同内容 → 重新插入暂存
        staging.stage("测试内容", "facts", 0.5)
        assert staging.count() == 1
        staging.close()

    def test_stage_promotion(self):
        """达到阈值后提升。"""
        promoted = []
        def callback(content_hash, content, layer, **kw):
            promoted.append((content, layer, kw.get("confidence")))

        staging = StagingArea(":memory:", promote_callback=callback)
        staging.stage("提升测试", "facts", 0.5)
        result = staging.stage("提升测试", "facts", 0.5)
        assert result["action"] == "promoted"
        assert len(promoted) == 1
        assert promoted[0][0] == "提升测试"
        assert promoted[0][1] == "facts"
        # 提升时置信度自动 +0.2
        assert promoted[0][2] == 0.7
        # 提升后从 staging 移除
        assert staging.count() == 0
        staging.close()

    def test_stage_multiple_items(self):
        """多条不同内容各自独立计数。
        PROMOTION_COUNT=2，所以内容A第二次出现时被提升并从 staging 移除。
        """
        promoted = []
        def cb(h, c, l, **kw):
            promoted.append(c)

        staging = StagingArea(":memory:", promote_callback=cb)
        staging.stage("内容A", "facts", 0.5)
        staging.stage("内容B", "facts", 0.5)
        r = staging.stage("内容A", "facts", 0.5)
        assert r["action"] == "promoted"  # A 被提升
        assert staging.count() == 1  # B 仍在
        assert len(promoted) == 1
        staging.close()

    def test_stage_empty_content(self):
        """空内容不暂存。"""
        staging = StagingArea(":memory:")
        result = staging.stage("", "facts", 0.5)
        assert result.get("action") == "discard"
        staging.close()

    def test_stage_list_by_layer(self):
        """按层列出暂存记录。"""
        staging = StagingArea(":memory:")
        staging.stage("事实1", "facts", 0.5)
        staging.stage("画像1", "profile", 0.5)
        facts = staging.list_staged(layer="facts")
        assert len(facts) == 1
        assert facts[0]["content"] == "事实1"
        staging.close()

    def test_stage_flush(self):
        """flush 强制提升所有暂存记录。"""
        promoted = []
        def callback(hash, content, layer, **kw):
            promoted.append(content)

        staging = StagingArea(":memory:", promote_callback=callback)
        staging.stage("内容1", "facts", 0.5)
        staging.stage("内容2", "facts", 0.5)
        count = staging.flush()
        assert count == 2
        assert len(promoted) == 2
        assert staging.count() == 0
        staging.close()


# ═══════════════════════════════════════════════════════════
# MemoryManager 整合测试
# ═══════════════════════════════════════════════════════════

class TestMemoryManagerConfidence:

    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.manager = MemoryManager(Path(self._tmp.name))

    def teardown_method(self):
        try:
            self.manager.close()
        except Exception:
            pass
        try:
            self._tmp.cleanup()
        except Exception:
            pass

    def test_write_high_confidence(self):
        """failure_learner → 直接写入。"""
        result = self.manager.store("profile", "用户叫小明", source="failure_learner")
        assert result["action"] == "write"
        assert result["confidence"] >= 0.7

    def test_stage_keyword_trigger(self):
        """关键词触发 → 暂存。"""
        result = self.manager.store("facts", "记住这个配置", source="remember_tool")
        assert result["action"] == "staged"
        assert result["confidence"] >= 0.4

    def test_discard_no_signal(self):
        """无信号 → 丢弃。"""
        result = self.manager.store("facts", "今天天气不错", source="auto")
        assert result["action"] == "discard"

    def test_promotion_on_repeat(self):
        """同内容第二次暂存 → 提升到正式层。"""
        self.manager.store("facts", "记住这个路径", source="remember_tool")
        result = self.manager.store("facts", "记住这个路径", source="remember_tool")
        assert result["action"] == "promoted"

    def test_promoted_content_searchable(self):
        """提升后内容可以被搜索到。"""
        self.manager.store("facts", "记住这个路径", source="remember_tool")
        self.manager.store("facts", "记住这个路径", source="remember_tool")
        results = self.manager.recall("路径")
        assert any("记住这个路径" in r.get("content", "") for r in results)

    def test_correction_plus_remember(self):
        """用户纠正 + 工具调用 → write（correction 信号优先生效）。"""
        result = self.manager.store(
            "profile", "用户是后端开发",
            source="remember_tool",
            user_msg="不对，我是后端开发",
        )
        # correction=0.9 覆盖 llm=0.3
        assert result["action"] == "write"
        assert result["confidence"] == 0.9

    def test_mixed_signals_take_highest(self):
        """多个信号时取最高分。"""
        result = self.manager.store(
            "facts", "记住不要用全局变量",
            source="failure_learner",
        )
        # failure=0.8, keyword=0.5 → write
        assert result["action"] == "write"
        assert result["confidence"] == 0.8

    def test_empty_content_skipped(self):
        """空内容直接丢弃。"""
        result = self.manager.store("facts", "", source="failure_learner")
        assert result["action"] == "discard"
        assert result.get("reason") == "empty_content"

    def test_discarded_not_searchable(self):
        """丢弃的内容不会出现在搜索结果中。"""
        self.manager.store("facts", "今天天气不错", source="auto")
        results = self.manager.recall("天气")
        assert not any("天气" in r.get("content", "") for r in results)

    def test_staged_not_searchable_until_promoted(self):
        """暂存的内容不会出现在搜索结果中（提升后才可见）。"""
        self.manager.store("facts", "记住这个秘密", source="remember_tool")
        results = self.manager.recall("秘密")
        assert not any("秘密" in r.get("content", "") for r in results)

    def test_consecutive_different_contents(self):
        """连续不同类型的写入各走各的。"""
        r1 = self.manager.store("profile", "用户叫小明", source="failure_learner")
        r2 = self.manager.store("facts", "记住这个配置", source="remember_tool")
        r3 = self.manager.store("facts", "随意文本", source="auto")
        assert r1["action"] == "write"
        assert r2["action"] == "staged"
        assert r3["action"] == "discard"
