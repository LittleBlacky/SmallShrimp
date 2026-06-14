from __future__ import annotations
"""Layered memory manager for persistent profile, facts, reflections, and sessions.

MemoryManager orchestrates MemoryProviders. 工具层通过 MemoryManager 的公开 API 读写记忆，
不直接调 Provider。
"""
from pathlib import Path
from typing import Iterable

from .provider import MemoryProvider, PromptBlock


class MemoryManager:
    """记忆管理器 — MemoryProvider 的纯代理层。

    工具层通过此类的公开方法操作记忆，不直接调 Provider。
    换后端只需换 Provider 实例，MemoryManager API 不变。
    """

    def __init__(self, provider_or_dir: MemoryProvider | str | Path):
        """初始化记忆管理器。

        Args:
            provider_or_dir: MemoryProvider 实例，或路径字符串（向后兼容，自动创建 BuiltinProvider）
        """
        if isinstance(provider_or_dir, (str, Path)):
            from .builtin.provider import BuiltinProvider
            self._provider: MemoryProvider = BuiltinProvider(memory_dir=Path(provider_or_dir))
        else:
            self._provider = provider_or_dir

    @property
    def provider(self) -> MemoryProvider:
        """获取底层 Provider（供高级用法和工具注册）。"""
        return self._provider

    def close(self) -> None:
        """关闭 Provider 后端连接。"""
        self._provider.close()

    def __del__(self) -> None:
        try:
            self._provider.close()
        except Exception:
            pass

    def initialize(self, session_id: str) -> None:
        self._provider.initialize(session_id)

    def system_prompt_block(self) -> str:
        return self._provider.system_prompt_block()

    def get_prompt_blocks(self) -> list[PromptBlock]:
        return self._provider.get_prompt_blocks()

    def prefetch(self, query: str, session_id: str = "") -> list[dict]:
        return self._provider.prefetch(query, session_id=session_id)

    def sync_turn(self, user_content: str, assistant_content: str,
                  session_id: str = "", messages: list | None = None) -> None:
        self._provider.sync_turn(user_content, assistant_content, session_id, messages)

    # ── 通用读写 API ────────────────────────────────────

    def store(self, layer: str, content: str, **kwargs) -> dict:
        return self._provider.store(layer, content, **kwargs)

    def recall(self, query: str, limit: int = 5, **kwargs) -> list[dict]:
        return self._provider.search(query, limit=limit, **kwargs)

    def list_all(self, **kwargs) -> list[dict]:
        return self._provider.list_all(**kwargs)

    def delete(self, record_id: str) -> bool:
        return self._provider.delete(record_id)

    def consolidate(self, **kwargs) -> int:
        return self._provider.consolidate(**kwargs)
