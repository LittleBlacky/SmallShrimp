"""Test LRU eviction in TopicMemory."""
import tempfile
from pathlib import Path

import pytest

from src.SmallShrimp.core.memory.memory_manager import TopicMemory


@pytest.fixture
def topic_memory():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield TopicMemory(Path(tmpdir), max_entries=5)


class TestRecallCount:
    """recall_count 计数测试。"""

    def test_new_record_starts_at_zero(self, topic_memory):
        r = topic_memory.store("用户喜欢 Python")
        assert r.get("recall_count", 0) == 0

    def test_search_increments_recall_count(self, topic_memory):
        topic_memory.store("用户喜欢 Python")
        results = topic_memory.search("Python")
        assert len(results) >= 1
        assert results[0].get("recall_count", 0) == 1

    def test_search_twice_counts_twice(self, topic_memory):
        topic_memory.store("用户喜欢 Python")
        topic_memory.search("Python")
        results = topic_memory.search("Python")
        assert results[0].get("recall_count", 0) == 2

    def test_search_no_query_no_count(self, topic_memory):
        """空查询不计次（list_all 场景）。"""
        topic_memory.store("用户喜欢 Python")
        results = topic_memory.search("")
        assert results[0].get("recall_count", 0) == 0

    def test_dedup_preserves_count(self, topic_memory):
        """去重时保留旧 recall_count（内容未变）。"""
        topic_memory.store("用户喜欢 Python")
        # 模拟被搜索过，先写入文件
        records = topic_memory._load_all()
        records[0]["recall_count"] = 5
        topic_memory._save_all(records)
        # 相同内容再次 store 会去重
        r2 = topic_memory.store("用户喜欢 Python")
        assert r2.get("recall_count", 0) == 5


class TestLRUEviction:
    """LRU 淘汰测试。"""

    def test_evicts_when_over_capacity(self, topic_memory):
        """超出 max_entries=5 时淘汰低 recall 记录。"""
        for i in range(7):
            topic_memory.store(f"记忆内容{i}")
        all_records = topic_memory.list_all()
        assert len(all_records) <= 5

    def test_evicts_lowest_recall_first(self, topic_memory):
        """recall_count 最低的最先被淘汰。"""
        # 存 5 条，搜索前 2 条提高它们的 recall_count
        topic_memory.store("Python 开发")       # recall=0
        topic_memory.store("深色模式偏好")       # recall=0
        topic_memory.store("用户喜欢 TypeScript")  # recall=0
        topic_memory.store("用户喜欢 Rust")       # recall=0
        topic_memory.store("午餐吃面条")          # recall=0

        # 给前两条加 recall
        topic_memory.search("Python")
        topic_memory.search("Python")
        topic_memory.search("深色")
        topic_memory.search("深色")

        # 再存 2 条触发淘汰
        topic_memory.store("新增记忆A")
        topic_memory.store("新增记忆B")

        all_records = topic_memory.list_all()
        assert len(all_records) <= 5
        # 高 recall 的应该还在
        contents = {r["content"] for r in all_records}
        assert "Python 开发" in contents
        assert "深色模式偏好" in contents

    def test_eviction_happens(self, topic_memory):
        """超出容量时淘汰低 recall 记录。"""
        for i in range(10):
            topic_memory.store(f"普通记忆{i}")
        all_records = topic_memory.list_all()
        assert len(all_records) <= 5  # max_entries=5

    def test_no_eviction_within_capacity(self, topic_memory):
        """不超过 max_entries 时不淘汰。"""
        for i in range(3):
            topic_memory.store(f"记忆{i}")
        assert len(topic_memory.list_all()) == 3
