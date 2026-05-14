"""命令基类。"""
from dataclasses import dataclass
from typing import Callable, Awaitable

@dataclass
class Command:
    """命令定义。"""
    name: str
    description: str
    usage: str  # 例如 "/skill <name>"
    handler: "CommandHandler"

CommandHandler = Callable[["CommandContext", list[str]], Awaitable[str]]