"""命令处理器实现。"""
from .base import Command, CommandHandler
from .registry import CommandRegistry
from ..skill_loader import SkillLoader

class CommandContext:
    """命令执行的上下文。"""
    def __init__(self, session: "AgentSession") -> None:
        self.session = session

async def cmd_skill(context: CommandContext, args: list[str]) -> str:
    """加载技能命令。"""
    if not args:
        return "用法: /skill <name>"
    skill_name = args[0]
    loader = SkillLoader()
    try:
        skill_def = loader.load(skill_name)
        return f"已加载技能 [{skill_name}]:\n\n{skill_def.content[:200]}..."
    except Exception as e:
        return f"技能 [{skill_name}] 不存在: {e}"

async def cmd_clear(context: CommandContext, args: list[str]) -> str:
    """清空会话命令。"""
    context.session.state.messages.clear()
    return "会话已清空"

async def cmd_help(context: CommandContext, args: list[str]) -> str:
    """帮助命令。"""
    commands = CommandRegistry.list_all()
    lines = ["可用命令:"]
    for cmd in commands:
        lines.append(f"  {cmd.usage} - {cmd.description}")
    return "\n".join(lines)

# 注册命令
CommandRegistry.register(Command(
    name="skill",
    description="加载技能内容",
    usage="/skill <name>",
    handler=cmd_skill,
))

CommandRegistry.register(Command(
    name="clear",
    description="清空当前会话",
    usage="/clear",
    handler=cmd_clear,
))

CommandRegistry.register(Command(
    name="help",
    description="显示可用命令",
    usage="/help",
    handler=cmd_help,
))