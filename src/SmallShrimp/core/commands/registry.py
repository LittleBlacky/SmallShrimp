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
    
    @classmethod
    def from_modules(cls, *modules):
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

def register_command(name: str, description: str, usage: str):
      def decorator(func):
          func._command_meta = {'name': name, 'description': description, 'usage': usage}
          return func
      return decorator