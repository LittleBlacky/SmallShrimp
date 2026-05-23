"""Layered memory eviction tests."""
import tempfile
from pathlib import Path

import pytest

from src.SmallShrimp.core.memory.memory_manager import LayeredMemoryStore


@pytest.fixture
def fact_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield LayeredMemoryStore(Path(tmpdir), "facts", max_entries=5)


class TestMemoryEviction:
    def test_no_eviction_within_capacity(self, fact_store):
        for index in range(3):
            fact_store.store(f"记忆{index}")
        assert len(fact_store.list_all()) == 3

    def test_evicts_when_over_capacity(self, fact_store):
        for index in range(7):
            fact_store.store(f"普通记忆{index}")
        assert len(fact_store.list_all()) == 5

    def test_evicts_low_importance_first(self, fact_store):
        fact_store.store("低重要度", importance=1)
        fact_store.store("高重要度", importance=10)
        for index in range(5):
            fact_store.store(f"新增记忆{index}", importance=5)
        contents = [record["content"] for record in fact_store.list_all()]
        assert "高重要度" in contents
        assert "低重要度" not in contents

    def test_search_increments_recall(self, fact_store):
        fact_store.store("Python 开发")
        fact_store.search("Python")
        fact_store.search("Python")
        assert fact_store.list_all()[0]["recall_count"] == 2
