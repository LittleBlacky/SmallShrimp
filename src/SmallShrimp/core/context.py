"""向后兼容别名 - SharedContext 已合并到 server/context.py 的 Context。"""
from __future__ import annotations

from ..server.context import Context as SharedContext  # noqa: F401