"""Phase 2.1 话题分段存储 - 测试与量化实验。

三种话题检测策略：
1. 显式信号: "换个话题""回到刚才" → 切换/回溯话题
2. 关键词回溯: 匹配历史话题关键词
3. 连续性: 处理追问和话题内延续
"""
from __future__ import annotations

import pytest
from src.SmallShrimp.core.topic_segmenter import TopicSegmenter, _tokenize, _jaccard_sim


class TestTopicDetectionStrategies:
    """三种检测策略的独立验证。"""

    def test_signal_switch_topic(self):
        """显式信号: '回到刚才' 回溯到上一个话题。"""
        seg = TopicSegmenter()
        seg.on_turn('帮我查天气', '', '10:00')
        r1 = seg.on_turn('换个话题聊聊电影', '', '10:01')
        # '换个话题'触发signal
        assert r1["match_method"] == "signal"
        r2 = seg.on_turn('推荐好看的', '', '10:02')
        # 推荐留在电影话题
        assert r2["topic_changed"] is False
        r3 = seg.on_turn('回到刚才', '', '10:03')
        # 回溯到上一个话题（天气）
        assert r3["match_method"] == "signal"
        assert "天气" in r3["new_topic"]

    def test_signal_back_to_previous(self):
        """显式信号: 回到刚才"""
        seg = TopicSegmenter()
        seg.on_turn('查天气', '', '10:00')
        seg.on_turn('订酒店', '', '10:01')
        result = seg.on_turn('回到刚才', '', '10:02')
        assert result["topic_changed"] is True
        # 应回到到上一个话题（查天气）
        assert "天气" in result["new_topic"]

    def test_continuity_keeps_same_topic(self):
        """追问保持在当前话题。"""
        seg = TopicSegmenter()
        seg.on_turn('帮我查一下北京的天气', '', '10:00')
        result = seg.on_turn('温度多少', '', '10:01')
        assert result["topic_changed"] is False
        assert result["match_method"] == "continuity"

    def test_new_message_after_topic_limit(self):
        """超出 MAX_ACTIVE_TOPICS 后自动裁剪。"""
        seg = TopicSegmenter()
        topics = ['查北京天气', '订酒店', '推荐餐厅', '买机票', '看新闻', '学编程']
        for i, t in enumerate(topics):
            seg.on_turn(t, '', f'10:0{i}')
        assert len(seg.segments) <= seg.MAX_ACTIVE_TOPICS


class TestTopicSummaryAndContext:
    """话题摘要和上下文组装验证。"""

    def test_build_summary_includes_active_topic(self):
        seg = TopicSegmenter()
        seg.on_turn('查北京的天气', '', '10:00')
        seg.on_turn('订一家酒店', '', '10:01')
        seg.on_turn('回到刚才', '', '10:02')
        summary = seg.build_summary()
        assert len(summary) > 0
        assert "查北京的天气" in summary or "天气" in summary

    def test_active_topic_marked(self):
        seg = TopicSegmenter()
        seg.on_turn('查天气', '', '10:00')
        seg.on_turn('订酒店', '', '10:01')
        seg.on_turn('回到刚才', '', '10:02')
        summary = seg.build_summary()
        # 活跃话题应标 🔄
        assert "🔄" in summary

    def test_to_dict_from_dict_roundtrip(self):
        seg = TopicSegmenter()
        seg.on_turn('查天气', '', '10:00')
        seg.on_turn('订酒店', '', '10:01')
        data = seg.to_dict()
        seg2 = TopicSegmenter()
        seg2.from_dict(data)
        assert len(seg2.segments) == len(seg.segments)
        assert seg2.segments[0].label == seg.segments[0].label


# ═══════════════════════════════════════════════════════════
# 量化实验
# ═══════════════════════════════════════════════════════════

class TestTopicDetectionQuantification:
    """话题检测量化指标。"""

    def test_topic_count_manageable(self):
        """量化: 10 轮模拟对话后话题数不超过 MAX_ACTIVE_TOPICS。"""
        seg = TopicSegmenter()
        topics = ['查天气', '订酒店', '推荐餐厅', '买机票', '看新闻', '学编程', '写代码', '听音乐', '健身', '购物']
        for i, t in enumerate(topics):
            if i > 0:
                seg.on_turn('换个话题', '', f'10:0{i}')
            seg.on_turn(t, '', f'10:0{i}')
        assert len(seg.segments) <= seg.MAX_ACTIVE_TOPICS
        assert len(seg.segments) > 0

    def test_signal_recall_accuracy(self):
        """量化: 显式信号召回准确率"""
        seg = TopicSegmenter()
        # 创建 3 个话题
        labels = []
        r = seg.on_turn('查一下北京的天气', '', '10:00')
        labels.append(r['new_topic'])
        seg.on_turn('换个话题', '', '10:01')
        r = seg.on_turn('订一家酒店', '', '10:02')
        labels.append(r['new_topic'])
        seg.on_turn('换个话题', '', '10:03')
        r = seg.on_turn('推荐好吃的', '', '10:04')
        labels.append(r['new_topic'])

        # "回到刚才" 应该回到上一个话题
        r = seg.on_turn('回到刚才', '', '10:05')
        assert r['topic_changed'] is True
        assert r['new_topic'] == labels[-2]  # 回到上一个（酒店）

    def test_topic_label_readable(self):
        """量化: 话题标签可读性（不应超过 15 字）"""
        seg = TopicSegmenter()
        r = seg.on_turn('帮我查一下北京的天气和温度', '', '10:00')
        label = r['new_topic']
        print(f"  话题标签: '{label}' ({len(label)} 字)")
        assert len(label) <= 15, f"标签过长: {label}"
        assert len(label) >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
