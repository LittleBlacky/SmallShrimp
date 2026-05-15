from .registry import register_command
from ..skill_loader import SkillLoader

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

@register_command(name="compact", description="压缩上下文命令", usage="/compact")
async def cmd_compact(context: CommandContext, args: list[str]) -> str:
    """手动压缩上下文命令。"""
    guard = context.session.agent.context_guard
    token_count = guard.estimate_tokens(context.session.state)

    # 先尝试截断
    context.session.state.messages = guard._truncate_large_tool_results(context.session.state.messages)

    # 检查是否需要进一步压缩
    new_token_count = guard.estimate_tokens(context.session.state)
    if new_token_count < guard.token_threshold:
        return f"已截断大工具结果。当前 tokens: {new_token_count} / {guard.token_threshold}"

    # 需要总结
    context.session.state = await guard._compact_messages(context.session.state)
    final_count = guard.estimate_tokens(context.session.state)
    return f"✓ 上下文已压缩。当前 tokens: {final_count} / {guard.token_threshold}，保留 {len(context.session.state.messages)} 条消息。"

@register_command(name="context", description="查看上下文使用情况", usage="/context")
async def cmd_context(context: CommandContext, args: list[str]) -> str:
    """查看当前上下文使用情况。"""
    guard = context.session.agent.context_guard
    token_count = guard.estimate_tokens(context.session.state)
    msg_count = len(context.session.state.messages)
    percentage = (token_count / guard.token_threshold) * 100

    return f"**Messages:** {msg_count}\n**Tokens:** {token_count} ({percentage:.1f}% of {guard.token_threshold} threshold)"