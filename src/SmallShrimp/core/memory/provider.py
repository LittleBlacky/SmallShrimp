"""Memory provider abstract base class.

所有存储后端必须实现此接口。MemoryManager 编排多个 Provider，工具层不直接调 Provider。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ── 记忆层声明 ──────────────────────────────────────────

class Layer:
    """声明式记忆层定义。

    Provider 通过类属性声明每层的语义、搜索和注入行为。
    系统自动收集所有 Layer 属性用于 get_prompt_blocks()、get_tools()、prefetch()。

    Args:
        name: 层名，如 "profile"、"notes"
        description: 该层的语义描述（LLM 看到）
        searchable: 是否可搜索
            False - 不生成检索工具
            True  - 生成 recall_{name} 工具
            "auto" - 生成工具 + 每轮自动 prefetch
        inject: 是否自动注入 system prompt
            None / ""  - 不注入
            "process"  - 进程级注入，永不刷新
            "session"  - 会话级注入，initialize() 时冻结
            "turn"     - 每轮重新注入
    """

    def __init__(self, name: str, description: str = "",
                 *,
                 searchable: bool | str = True,
                 inject: str | None = None):
        self.name = name
        self.description = description
        self.searchable = searchable
        self.inject = inject

    def __set_name__(self, owner: type, name: str) -> None:
        """当 Layer 被赋值到类属性时自动补齐 name（不覆盖显式传入的 name）。"""
        if not hasattr(self, '_name_set'):
            self.name = name
            self._name_set = True

    def __repr__(self) -> str:
        return f"Layer({self.name!r}, searchable={self.searchable!r}, inject={self.inject!r})"


@dataclass
class PromptBlock:
    """要注入 system prompt 的内容块。"""
    name: str                                 # 段标题，如 "User Profile"
    content: str                              # Markdown 内容
    cache_tier: str = "session"               # "process" | "session" | "turn"


class MemoryProvider(ABC):
    """存储后端的抽象接口。

    工具层通过 MemoryProvider 的子类公开 API 读写记忆。
    自定义后端只需实现 store / search / list_all / delete 五个核心方法，
    其余方法都有默认空实现。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 唯一标识，如 'builtin', 'honcho'."""

    @abstractmethod
    def is_available(self) -> bool:
        """检查后端是否可用（如数据库连接正常）。"""

    # ── 生命周期 ────────────────────────────────────────

    def initialize(self, session_id: str) -> None:
        """初始化会话级缓存（默认空实现）。"""

    def shutdown(self) -> None:
        """关闭后端连接，释放资源（默认空实现）。"""

    def close(self) -> None:
        """关闭后端连接（默认空实现）。"""

    # ── 层声明 ──────────────────────────────────────────

    @property
    def layers(self) -> dict[str, Layer]:
        """自动收集此类中所有的 Layer 声明。"""
        result: dict[str, Layer] = {}
        for attr_name in dir(type(self)):
            attr = getattr(type(self), attr_name, None)
            if isinstance(attr, Layer):
                result[attr.name] = attr
        return result

    # ── System Prompt ───────────────────────────────────

    def get_prompt_blocks(self) -> list[PromptBlock]:
        """根据 layers 的 inject 声明自动生成注入内容块。

        覆写此方法可自定义注入逻辑。默认行为：
        - 遍历 self.layers
        - 对 inject 不为 None 的层，调 _load_layer() 获取内容
        - 返回 PromptBlock 列表
        """
        blocks: list[PromptBlock] = []
        for layer in self.layers.values():
            if layer.inject:
                content = self._load_layer(layer.name)
                if content:
                    blocks.append(PromptBlock(layer.description or layer.name, content, cache_tier=layer.inject))
        return blocks

    def _load_layer(self, layer: str) -> str:
        """读取某层的全部内容（默认空实现，供 get_prompt_blocks 调用）。"""
        return ""

    def system_prompt_block(self) -> str:
        """（旧接口）返回注入 system prompt 的缓存快照。

        默认委托 get_prompt_blocks() 取第一段。
        """
        blocks = self.get_prompt_blocks()
        return blocks[0].content if blocks else ""

    # ── 前置召回 ────────────────────────────────────────

    def prefetch(self, query: str, session_id: str = "") -> list[dict]:
        """根据 layers 的 searchable='auto' 声明自动召回相关记忆。

        默认遍历 self.layers，对 searchable='auto' 的层自动 search()。
        """
        results: list[dict] = []
        for layer in self.layers.values():
            if layer.searchable == "auto":
                results.extend(self.search(query, layer=layer.name, limit=5))
        return results[:5]

    # ── 后置同步 ────────────────────────────────────────

    def sync_turn(self, user_content: str, assistant_content: str,
                  session_id: str = "", messages: list[dict] | None = None) -> None:
        """持久化本轮对话（默认空实现）。"""

    # ── 存储接口 ────────────────────────────────────────

    @abstractmethod
    def store(self, layer: str, content: str, **kwargs: Any) -> dict:
        """写入一条记忆记录。

        Args:
            layer: 记忆层名（字符串，Provider 自己定义含义）
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

    # ── 工具注册 ────────────────────────────────────────

    @abstractmethod
    def get_tools(self) -> list:
        """返回此 Provider 提供的一组 Tool 对象。

        Tool 对象由 @tool 装饰器创建，系统自动注册到 ToolRegistry。
        示例见 BuiltinProvider。
        """
        ...

    # ── 删除 / 合并 ──────────────────────────────────────

    def delete(self, record_id: str) -> bool:
        """删除一条记录（默认返回 False）。"""
        return False

    def consolidate(self, **kwargs: Any) -> int:
        """合并相似记录（默认返回 0）。"""
        return 0

    # ── 可选钩子 ────────────────────────────────────────

    def on_turn_start(self, message: str, session_id: str = "") -> None:
        """每轮开始时的回调（默认空实现）。"""

    def on_session_end(self, session_id: str) -> None:
        """会话结束时的回调（默认空实现）。"""

    def on_memory_write(self, action: str, target: str, content: str,
                        metadata: dict | None = None) -> None:
        """记忆写入时的回调（默认空实现）。"""
