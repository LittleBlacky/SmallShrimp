"""命令注册表。"""
from .base import Command

class CommandRegistry:
    """管理命令的注册和查找。"""
    _commands: dict[str, Command] = {}

    @classmethod
    def register(cls, command: Command) -> None:
        cls._commands[command.name] = command

    @classmethod
    def get(cls, name: str) -> Command | None:
        return cls._commands.get(name)

    @classmethod
    def list_all(cls) -> list[Command]:
        return list(cls._commands.values())

    @classmethod
    def parse(cls, user_input: str) -> tuple[str, list[str]] | None:
        """解析用户输入，返回 (命令名, 参数列表)。"""
        if not user_input.startswith("/"):
            return None
        parts = user_input[1:].split(maxsplit=1)
        name = parts[0]
        args = parts[1].split() if len(parts) > 1 else []
        return (name, args)