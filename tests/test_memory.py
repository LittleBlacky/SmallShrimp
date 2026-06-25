from __future__ import annotations
"""Layered Memory Manager 测试。"""
import tempfile
from pathlib import Path

from src.SmallShrimp.core.memory.builtin.file_store import MarkdownStore
from src.SmallShrimp.core.memory.memory_manager import MemoryManager
from src.SmallShrimp.core.message import HumanMessage, SystemMessage


def test_memory_manager_init():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))
        try:
            assert manager.provider.memory_dir.exists()
            assert (manager.provider.memory_dir / ".index.db").exists()
        finally:
            manager.close()


def test_markdown_store_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = MarkdownStore(Path(tmpdir))
        try:
            first = store.store("facts", "用户喜欢 Python 编程")
            assert first["id"] is not None

            results = store.search("Python", layer="facts")
            assert len(results) >= 1

            assert store.delete(first["id"]) is True
            results_after = store.search("Python", layer="facts")
            assert len(results_after) == 0
        finally:
            store.close()


def test_profile_is_separate_from_recall():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))
        try:
            manager.provider.store("profile", "用户叫 Zane")
            manager.provider.store("facts", "用户喜欢 Python")

            profile = manager.provider.list_all(layer="profile")
            assert any("Zane" in record["content"] for record in profile)

            fact_results = manager.provider.search("Python", layer="facts")
            assert any("Python" in record["content"] for record in fact_results)
        finally:
            manager.close()


def test_store_routes_to_layers():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))
        try:
            p = manager.provider
            rec1 = p.store("profile", "用户长期偏好中文")
            assert rec1["layer"] == "profile"

            rec2 = p.store("facts", "普通事实")
            assert rec2["layer"] == "facts"

            rec3 = p.store("projects", "项目使用 pytest")
            assert rec3["layer"] == "projects"

            rec4 = p.store("reflections", "失败后先读测试")
            assert rec4["layer"] == "reflections"
        finally:
            manager.close()


def test_inject_memories_get_prompt_blocks():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))
        try:
            manager.provider.store("profile", "用户叫 Zane")
            manager.provider.initialize("test-session")
            blocks = manager.provider.get_prompt_blocks()
            assert any("Zane" in b.content for b in blocks if b.name == "User Profile")
        finally:
            manager.close()
