"""Test memory deduplication in TopicMemory.store()."""
import tempfile
from pathlib import Path

import pytest

from src.SmallShrimp.core.memory.memory_manager import TopicMemory


@pytest.fixture
def topic_memory():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield TopicMemory(Path(tmpdir))


class TestMemoryDedup:
    """去重测试：store() 应合并相似记忆而非新增。"""

    def test_exact_duplicate_merges(self, topic_memory):
        """精确重复 → 更新旧记录，不新增。"""
        r1 = topic_memory.store("用户喜欢 Python")
        r2 = topic_memory.store("用户喜欢 Python")
        all_records = topic_memory.list_all()
        assert len(all_records) == 1
        assert r2["id"] == r1["id"]

    def test_substring_duplicate_merges(self, topic_memory):
        """新内容是旧内容的子串 → 合并。"""
        r1 = topic_memory.store("用户喜欢用 Python 做后端开发")
        r2 = topic_memory.store("喜欢用 Python")
        all_records = topic_memory.list_all()
        assert len(all_records) == 1
        assert r2["id"] == r1["id"]

    def test_near_duplicate_merges(self, topic_memory):
        """高度相似（新内容为旧内容子串）→ 合并。"""
        r1 = topic_memory.store("用户偏好深色主题界面布局")
        r2 = topic_memory.store("偏好深色主题界面")
        all_records = topic_memory.list_all()
        assert len(all_records) == 1
        assert r2["id"] == r1["id"]

    def test_different_content_adds_new(self, topic_memory):
        """完全不同 → 正常新增。"""
        topic_memory.store("用户喜欢 Python")
        topic_memory.store("用户偏好深色模式")
        all_records = topic_memory.list_all()
        assert len(all_records) == 2

    def test_updated_at_refreshes_on_dedup(self, topic_memory):
        """去重时 updated_at 应刷新。"""
        r1 = topic_memory.store("用户喜欢 Python")
        import time
        time.sleep(0.1)
        r2 = topic_memory.store("用户喜欢 Python")
        assert r2["updated_at"] > r1["updated_at"]
