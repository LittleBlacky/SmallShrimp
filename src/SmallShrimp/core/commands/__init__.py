from .registry import register_command, CommandRegistry
from . import handlers
CommandRegistry.from_modules(handlers)