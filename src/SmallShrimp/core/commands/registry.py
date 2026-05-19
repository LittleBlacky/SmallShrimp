from __future__ import annotations
"""命令注册表。"""
from .base import Command

_commands: dict[str, Command] = {}

def _get_commands() -> dict[str, Command]:
    return _commands

class CommandRegistry:
    """管理命令的注册和查找。"""

    @property
    def _commands(self) -> dict[str, Command]:
        return _commands

    @classmethod
    def clear(cls) -> None:
        """清空所有注册的命令。"""
        _commands.clear()

    @classmethod
    def register(cls, command: Command) -> None:
        _commands[command.name] = command

    @classmethod
    def get(cls, name: str) -> Command | None:
        return _commands.get(name)

    @classmethod
    def list_all(cls) -> list[Command]:
        return list(_commands.values())

    @classmethod
    def parse(cls, user_input: str) -> tuple[str, list[str]] | None:
        """解析用户输入，返回 (命令名, 参数列表)。"""
        if not user_input.startswith("/"):
            return None
        parts = user_input[1:].split(maxsplit=1)
        name = parts[0]
        args = parts[1].split() if len(parts) > 1 else []
        return (name, args)

    @classmethod
    async def dispatch(cls, user_input: str, context: "CommandContext") -> "str | None":
        """异步解析并执行命令。"""
        parsed = cls.parse(user_input)
        if not parsed:
            return None
        name, args = parsed
        cmd = cls.get(name)
        if not cmd or not cmd.handler:
            return None
        return await cmd.handler(context, args)

    @classmethod
    def from_modules(cls, *modules) -> None:
        """从模块自动注册命令。"""
        for module in modules:
            for name, obj in vars(module).items():
                if callable(obj) and hasattr(obj, '_command_meta'):
                    meta = obj._command_meta
                    cls.register(Command(
                        name=meta['name'],
                        description=meta['description'],
                        usage=meta['usage'],
                        handler=obj,
                    ))

    @classmethod
    def with_builtins(cls) -> "CommandRegistry":
        """创建注册表并注册所有内置命令。"""
        from ..commands import handlers
        cls.from_modules(handlers)
        return cls


def register_command(name: str, description: str, usage: str):
      def decorator(func):
          func._command_meta = {'name': name, 'description': description, 'usage': usage}
          return func
      return decorator