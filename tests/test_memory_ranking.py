from __future__ import annotations
"""记忆混合词法评分测试。"""
from src.SmallShrimp.core.memory.memory_manager import _rank_memory


def test_exact_match_highest():
    """精确匹配得分最高。"""
    assert _rank_memory("dark mode", "dark mode preference") > 7.0

def test_substring_in_score():
    """子串匹配得分。"""
    s = _rank_memory("dark mode", "user prefers dark mode in editor")
    assert s > 7.0  # 子串匹配 +8

def test_partial_overlap_scores():
    """部分重叠有分（中文字符 n-gram）。"""
    s = _rank_memory("颜色主题", "用户偏好深色颜色主题界面")
    assert s > 2.0  # n-gram: "颜色" 共享 2-gram

def test_unrelated_zero():
    """无关内容零分。"""
    s = _rank_memory("端口配置", "用户喜欢 Python 3.11")
    assert s < 1.0  # 几乎不匹配

def test_cjk_char_ngram():
    """中文 n-gram 匹配。"""
    s = _rank_memory("颜色", "用户偏好深色颜色主题")
    assert s > 3.0  # n-gram: "颜色"

def test_ranking_sorts_correctly():
    """评分排序：匹配度高的在前。"""
    s1 = _rank_memory("dark mode", "dark mode preference for all apps")
    s2 = _rank_memory("dark mode", "user likes python version 3.11")
    assert s1 > s2


if __name__ == "__main__":
    test_exact_match_highest()
    test_substring_in_score()
    test_partial_overlap_scores()
    test_unrelated_zero()
    test_cjk_char_ngram()
    test_ranking_sorts_correctly()
    print("All memory ranking tests passed!")
