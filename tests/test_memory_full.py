"""MarkdownStore 完整的增删查改测试。"""
import tempfile
from pathlib import Path

from src.SmallShrimp.core.memory.builtin.file_store import MarkdownStore


def test_store_basic():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = MarkdownStore(Path(tmpdir))
        try:
            record = store.store("facts", "用户偏好 Python")
            assert record["content"] == "用户偏好 Python"
            assert record["layer"] == "facts"
            assert "id" in record
        finally:
            store.close()


def test_store_search_by_keyword():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = MarkdownStore(Path(tmpdir))
        try:
            store.store("facts", "用户喜欢 dark mode")
            store.store("facts", "项目名叫 SmallShrimp")
            store.store("facts", "用户偏好 Python")
            results = store.search("Python", layer="facts")
            assert len(results) >= 1
            assert "Python" in results[0]["content"]
        finally:
            store.close()


def test_store_delete():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = MarkdownStore(Path(tmpdir))
        try:
            record = store.store("facts", "待删除")
            assert store.delete(record["id"]) is True
            assert store.delete(record["id"]) is False
        finally:
            store.close()


def test_store_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        store1 = MarkdownStore(Path(tmpdir))
        store1.store("facts", "持久化内容")
        store1.close()
        store2 = MarkdownStore(Path(tmpdir))
        try:
            results = store2.search("持久化", layer="facts")
            assert len(results) >= 1
            assert results[0]["content"] == "持久化内容"
        finally:
            store2.close()
