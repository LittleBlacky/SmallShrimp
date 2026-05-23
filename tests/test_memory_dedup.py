"""Layered memory deduplication tests."""
import tempfile
from pathlib import Path

import pytest

from src.SmallShrimp.core.memory.memory_manager import LayeredMemoryStore


@pytest.fixture
def fact_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield LayeredMemoryStore(Path(tmpdir), "facts")


class TestMemoryDedup:
    def test_exact_duplicate_merges(self, fact_store):
        first = fact_store.store("用户喜欢 Python")
        second = fact_store.store("用户喜欢 Python")
        assert len(fact_store.list_all()) == 1
        assert second["id"] == first["id"]

    def test_substring_duplicate_merges(self, fact_store):
        first = fact_store.store("用户喜欢用 Python 做后端开发")
        second = fact_store.store("喜欢用 Python")
        assert len(fact_store.list_all()) == 1
        assert second["id"] == first["id"]

    def test_different_content_adds_new(self, fact_store):
        fact_store.store("用户喜欢 Python")
        fact_store.store("用户偏好深色模式")
        assert len(fact_store.list_all()) == 2

    def test_metadata_updates_on_dedup(self, fact_store):
        first = fact_store.store("用户喜欢 Python", importance=4)
        second = fact_store.store("用户喜欢 Python", importance=8)
        assert second["id"] == first["id"]
        assert second["importance"] == 8

    def test_dedup_is_layer_local(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            profile = LayeredMemoryStore(root, "profile")
            facts = LayeredMemoryStore(root, "facts")
            profile.store("用户喜欢 Python")
            facts.store("用户喜欢 Python")
            assert len(profile.list_all()) == 1
            assert len(facts.list_all()) == 1
