from __future__ import annotations
"""Memory system for persistent knowledge and recall."""
from pathlib import Path

from .memory_manager import MemoryManager
from .provider import MemoryProvider, PromptBlock, Layer
from .builtin.provider import BuiltinProvider


def create_memory_manager(config: dict) -> MemoryManager:
    """从配置创建 MemoryManager。

    Args:
        config: 顶层配置字典（含 workspace, memory 等键）
    """
    mc = config.get("memory", {})
    provider_name = mc.get("provider", "builtin")
    workspace = Path(config.get("workspace", "."))

    if provider_name == "builtin":
        provider = BuiltinProvider(
            memory_dir=workspace / "memories",
            embedding_config=mc.get("embedding"),
        )
    else:
        provider = _load_provider(provider_name, config)

    return MemoryManager(provider)


def _load_provider(dotted_path: str, config: dict) -> MemoryProvider:
    """从 dotted path 动态加载 Provider。"""
    import importlib
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls(config)


__all__ = [
    "MemoryManager", "MemoryProvider", "BuiltinProvider",
    "PromptBlock", "Layer", "create_memory_manager",
]