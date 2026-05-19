"""Memory manager for long-term knowledge retention."""
from __future__ import annotations

import json
from pathlib import Path


class MemoryManager:
    """管理跨会话的持久化记忆。"""

    def __init__(self, memories_dir: Path) -> None:
        self.memories_dir = Path(memories_dir)
        self.memories_dir.mkdir(parents=True, exist_ok=True)

    def remember(self, content: str, tags: list[str] | None = None) -> None:
        """保存一条记忆。"""
        entry = {
            "content": content,
            "tags": tags or [],
        }
        idx = len(list(self.memories_dir.glob("*.json")))
        (self.memories_dir / f"{idx:04d}.json").write_text(
            json.dumps(entry, ensure_ascii=False)
        )

    def recall(self, query: str | None = None) -> list[dict]:
        """检索所有记忆（简单实现）。"""
        results = []
        for f in sorted(self.memories_dir.glob("*.json")):
            try:
                entry = json.loads(f.read_text(encoding="utf-8"))
                if query and query.lower() not in entry.get("content", "").lower():
                    continue
                results.append(entry)
            except (json.JSONDecodeError, OSError):
                pass
        return results
