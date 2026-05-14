from .registry import register_command

class CommandContext:
    """命令执行的上下文。"""
    def __init__(self, session: "AgentSession") -> None:
        self.session = session

@register_command(name="skill", description="加载技能内容", usage="/skill <name>")
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

@register_command(name="clear", description="清空会话命令", usage="/clear")
async def cmd_clear(context: CommandContext, args: list[str]) -> str:
    """清空会话命令。"""
    context.session.state.messages.clear()
    return "会话已清空"

@register_command(name="help", description="帮助命令", usage="/help")
async def cmd_help(context: CommandContext, args: list[str]) -> str:
    """帮助命令。"""
    from .registry import CommandRegistry
    commands = CommandRegistry.list_all()
    lines = ["可用命令:"]
    for cmd in commands:
        lines.append(f"  {cmd.usage} - {cmd.description}")
    return "\n".join(lines)