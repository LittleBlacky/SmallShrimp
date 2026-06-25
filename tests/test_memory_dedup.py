"""MarkdownStore 基本 CRUD 测试。"""
import tempfile
from pathlib import Path

import pytest

from src.SmallShrimp.core.memory.builtin.file_store import MarkdownStore


@pytest.fixture
def fact_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = MarkdownStore(Path(tmpdir))
        try:
            yield store
        finally:
            store.close()


class TestMemoryStore:
    def test_store_creates_records(self, fact_store):
        first = fact_store.store("facts", "用户喜欢 Python")
        assert first["id"] is not None
        assert first["content"] == "用户喜欢 Python"

    def test_search_finds_by_layer(self, fact_store):
        fact_store.store("facts", "用户喜欢 Python")
        fact_store.store("facts", "用户偏好深色模式")
        results = fact_store.search("Python", layer="facts")
        assert len(results) >= 1
