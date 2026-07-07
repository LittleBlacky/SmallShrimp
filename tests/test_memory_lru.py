"""MemoryStore 基本存储测试（当前实现无 LRU 淘汰）。"""
import tempfile
from pathlib import Path

import pytest

from src.SmallShrimp.core.memory.builtin.file_store import MemoryStore


@pytest.fixture
def fact_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = MemoryStore(Path(tmpdir) / "test.db")
        try:
            yield store
        finally:
            store.close()


class TestMemoryStore:
    def test_basic_write_and_read(self, fact_store):
        for index in range(3):
            fact_store.store("facts", f"记忆{index}")
        results = fact_store.search("记忆", layer="facts")
        assert len(results) >= 3
