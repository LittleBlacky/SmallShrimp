"""Memory provider abstract base class.

所有存储后端必须实现此接口。MemoryManager 编排多个 Provider，工具层不直接调 Provider。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MemoryProvider(ABC):
    """存储后端的抽象接口。

    工具层通过 MemoryManager 的公开 API 读写记忆，MemoryManager 内部路由到 Provider。
    Provider 不暴露工具接口（无 get_tool_schemas / handle_tool_call）。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 唯一标识，如 'builtin', 'honcho'."""

    @abstractmethod
    def is_available(self) -> bool:
        """检查后端是否可用（如数据库连接正常）。"""

    # ── 生命周期 ────────────────────────────────────────

    @abstractmethod
    def initialize(self, session_id: str) -> None:
        """初始化会话级缓存。从数据库读取 profile 等快照到内存。

        本轮内写入不更新此缓存，新记忆从下一轮/新会话可见。
        """

    @abstractmethod
    def shutdown(self) -> None:
        """关闭后端连接，释放资源。"""

    def close(self) -> None:
        """关闭后端连接（默认委托给 shutdown）。"""

    # ── System Prompt ───────────────────────────────────

    @abstractmethod
    def system_prompt_block(self) -> str:
        """返回注入 system prompt 的缓存快照。

        关键缓存契约：
        - initialize() 时从数据库读取一次，缓存到内存
        - 每轮调用返回内存缓存快照，不查数据库
        - 保证 system prompt 字节级稳定，不破坏 prefix cache
        """

    # ── 前置召回 ────────────────────────────────────────

    @abstractmethod
    def prefetch(self, query: str, session_id: str = "") -> list[dict]:
        """根据查询自动召回相关记忆，结果注入 user message 尾部。"""

    # ── 后置同步 ────────────────────────────────────────

    @abstractmethod
    def sync_turn(self, user_content: str, assistant_content: str,
                  session_id: str = "", messages: list[dict] | None = None) -> None:
        """持久化本轮对话（sessions 层）。"""

    # ── 存储接口 ────────────────────────────────────────

    @abstractmethod
    def store(self, layer: str, content: str, **kwargs: Any) -> dict:
        """写入一条记忆记录。

        Args:
            layer: 记忆层 (profile/facts/projects/reflections/sessions)
            content: 记忆内容
            **kwargs: source, importance, confidence 等可选字段
        Returns:
            写入后的完整记录 dict
        """

    @abstractmethod
    def search(self, query: str, layer: str | None = None, **kwargs: Any) -> list[dict]:
        """检索记忆记录。

        Args:
            query: 检索关键词
            layer: 指定层，None 表示跨层检索
            **kwargs: limit 等可选参数
        Returns:
            按相关性排序的记录列表
        """

    @abstractmethod
    def list_all(self, layer: str | None = None, **kwargs: Any) -> list[dict]:
        """列出所有记录（用于初始化快照等）。"""

    # ── 可选钩子 ────────────────────────────────────────

    def on_turn_start(self, message: str, session_id: str = "") -> None:
        """每轮开始时的回调（默认空实现）。"""

    def on_session_end(self, session_id: str) -> None:
        """会话结束时的回调（默认空实现）。"""

    def on_memory_write(self, action: str, target: str, content: str,
                        metadata: dict | None = None) -> None:
        """记忆写入时的回调（默认空实现）。"""
