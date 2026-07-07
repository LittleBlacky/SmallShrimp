from __future__ import annotations
"""Layered Memory Manager 测试。"""
import tempfile
import sqlite3
from pathlib import Path

from src.SmallShrimp.core.memory.builtin.file_store import MemoryStore
from src.SmallShrimp.core.memory.memory_manager import MemoryManager
from src.SmallShrimp.core.runtime.message import HumanMessage, SystemMessage


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
        store = MemoryStore(Path(tmpdir) / "test.db")
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


def test_memory_store_migrates_legacy_schema_missing_deleted_column():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "legacy.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE memory_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                layer TEXT NOT NULL,
                content TEXT NOT NULL,
                entity_type TEXT NOT NULL DEFAULT '',
                access_count INTEGER NOT NULL DEFAULT 0,
                source_turn_id TEXT NOT NULL DEFAULT '',
                source_text TEXT NOT NULL DEFAULT '',
                importance INTEGER NOT NULL DEFAULT 5,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE memory_fts
            USING fts5(content_jieba, content_raw, tokenize='unicode61');
            """
        )
        conn.commit()
        conn.close()

        store = MemoryStore(db_path)
        try:
            record = store.store("facts", "旧库迁移后可以继续写入")
            assert record["id"] is not None
            assert store.delete(record["id"]) is True
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
