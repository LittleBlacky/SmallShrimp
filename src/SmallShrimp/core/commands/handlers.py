from __future__ import annotations
from typing import TYPE_CHECKING

from .registry import register_command
from ..skill_loader import SkillLoader
from ..memory import MemoryManager

if TYPE_CHECKING:
    from ..routing import RoutingTable
    from ..agent import AgentSession

class CommandContext:
    """命令执行的上下文。"""
    def __init__(
        self,
        session: "AgentSession",
        routing_table: "RoutingTable | None" = None,
    ) -> None:
        self.session = session
        self.routing_table = routing_table
        self._memory_manager: MemoryManager | None = None

    @property
    def memory(self) -> MemoryManager:
        if self._memory_manager is None:
            from pathlib import Path
            self._memory_manager = MemoryManager(Path("workspace/memories"))
        return self._memory_manager

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

@register_command(name="remember", description="保存记忆", usage="/remember <content>")
async def cmd_remember(context: CommandContext, args: list[str]) -> str:
    """保存记忆。"""
    if not args:
        return "用法: /remember <内容>\n例如: /remember 用户喜欢用 dark mode"
    content = " ".join(args)
    # 尝试提取标签 (#tag 格式)
    import re
    tags = re.findall(r"#(\w+)", content)
    content_clean = re.sub(r"#\w+", "", content).strip()

    record = context.memory.remember(content_clean, tags=tags if tags else None)
    tag_str = f" [#{'/'.join(tags)}]" if tags else ""
    return f"✓ 已记住: {record['content'][:100]}{tag_str}"

@register_command(name="recall", description="搜索记忆", usage="/recall <query>")
async def cmd_recall(context: CommandContext, args: list[str]) -> str:
    """搜索记忆。"""
    if not args:
        return "用法: /recall <查询词>\n例如: /recall dark mode"
    query = " ".join(args)
    results = context.memory.recall(query)
    if not results:
        return f"没有找到关于 '{query}' 的记忆"
    lines = [f"找到 {len(results)} 条相关记忆:\n"]
    for r in results:
        tags_str = f"[#{'/'.join(r['tags'])}]" if r.get("tags") else ""
        lines.append(f"  • {r['content'][:80]}... {tags_str}")
    return "\n".join(lines)

@register_command(name="memories", description="查看所有记忆", usage="/memories")
async def cmd_memories(context: CommandContext, args: list[str]) -> str:
    """列出所有记忆。"""
    records = context.memory.topics.list_all()
    if not records:
        return "还没有任何记忆。使用 /remember <内容> 来添加。"
    lines = [f"共 {len(records)} 条记忆:\n"]
    for r in records:
        tags_str = f"[#{'/'.join(r['tags'])}]" if r.get("tags") else ""
        date_str = r["created_at"][:10]
        lines.append(f"  [{date_str}] {r['content'][:60]}... {tags_str}")
    return "\n".join(lines)

@register_command(name="forget", description="删除记忆", usage="/forget <关键词>")
async def cmd_forget(context: CommandContext, args: list[str]) -> str:
    """删除记忆。"""
    if not args:
        return "用法: /forget <关键词>\n将删除匹配的记忆"
    query = " ".join(args)
    results = context.memory.recall(query, limit=20)
    if not results:
        return f"没有找到匹配 '{query}' 的记忆"
    deleted = 0
    for r in results:
        if context.memory.topics.delete(r["id"]):
            deleted += 1
    return f"已删除 {deleted} 条记忆"

@register_command(name="note", description="写入今日笔记", usage="/note <content>")
async def cmd_note(context: CommandContext, args: list[str]) -> str:
    """写入今日笔记。"""
    if not args:
        return "用法: /note <内容>\n例如: /note 完成了记忆模块开发"
    content = " ".join(args)
    context.memory.today_note(content)
    return "✓ 已写入今日笔记"

@register_command(name="notes", description="查看近期笔记", usage="/notes [days]")
async def cmd_notes(context: CommandContext, args: list[str]) -> str:
    """列出近期笔记。"""
    limit = int(args[0]) if args else 7
    notes = context.memory.daily.list_notes(limit=limit)
    if not notes:
        return "暂无笔记"
    lines = [f"近期 {len(notes)} 篇笔记:\n"]
    for n in notes:
        lines.append(f"  📅 {n['date']} ({n['size']} bytes)")
    return "\n".join(lines)


# ── Cron 定时任务命令 ──

@register_command(name="cron", description="管理定时任务", usage="/cron <add|list|delete> [args]")
async def cmd_cron(context: CommandContext, args: list[str]) -> str:
    """管理定时任务。"""
    if not args:
        return "用法:\n  /cron add <schedule> <name> [agent] [内容...]\n  /cron list\n  /cron delete <id>"

    subcmd = args[0].lower()

    if subcmd == "list":
        return _cron_list(context)

    if subcmd == "delete":
        if len(args) < 2:
            return "用法: /cron delete <id>"
        return _cron_delete(context, args[1])

    if subcmd == "add":
        if len(args) < 3:
            return "用法: /cron add <schedule> <name> [agent] [内容...]\n例如: /cron add \"0 9 * * *\" morning-report pickle 发送每日早报"
        schedule = args[1]
        name = args[2]
        agent = args[3] if len(args) > 3 else "pickle"
        prompt = " ".join(args[4:]) if len(args) > 4 else name
        return _cron_add(context, schedule, name, agent, prompt)

    return f"未知子命令: {subcmd}"


def _cron_add(context: CommandContext, schedule: str, name: str, agent: str, prompt: str) -> str:
    """创建定时任务。"""
    from pathlib import Path
    from ..cron_loader import CronLoader

    crons_dir = Path("workspace/crons")
    cron_id = name.lower().replace(" ", "-")

    cron_dir = crons_dir / cron_id
    cron_dir.mkdir(parents=True, exist_ok=True)

    yaml_content = f"""---
name: {name}
schedule: "{schedule}"
agent: {agent}
---
{prompt}
"""
    (cron_dir / "CRON.md").write_text(yaml_content, encoding="utf-8")

    return f"✓ 已创建定时任务 `{cron_id}`:\n  名称: {name}\n  计划: {schedule}\n  Agent: {agent}"


def _cron_list(context: CommandContext) -> str:
    """列出所有定时任务。"""
    from pathlib import Path
    from ..cron_loader import CronLoader

    crons_dir = Path("workspace/crons")
    loader = CronLoader(crons_dir)
    jobs = loader.discover_crons()

    if not jobs:
        return "暂无定时任务。使用 /cron add 创建。"

    lines = ["定时任务列表:"]
    for job in jobs:
        one_off_mark = " [一次性]" if job.one_off else ""
        lines.append(f"  • `{job.id}`{one_off_mark} - {job.schedule} → {job.agent}")
    return "\n".join(lines)


def _cron_delete(context: CommandContext, cron_id: str) -> str:
    """删除定时任务。"""
    import shutil
    from pathlib import Path

    cron_path = Path("workspace/crons") / cron_id
    if not cron_path.exists():
        return f"定时任务 `{cron_id}` 不存在。"

    shutil.rmtree(cron_path)
    return f"✓ 已删除定时任务 `{cron_id}`"


# ── 路由管理命令 ──

@register_command(name="route", description="添加路由规则", usage="/route <pattern> <agent>")
async def cmd_route(context: CommandContext, args: list[str]) -> str:
    """添加路由绑定。"""
    if len(args) < 2:
        return "用法: /route <source_pattern> <agent_id>\n例如: /route platform-telegram:.* cookie"
    pattern, agent_id = args[0], args[1]
    table = context.routing_table
    if table is None:
        return "路由表不可用（需 Server 模式）"
    table.persist_binding(pattern, agent_id)
    return f"✓ 已绑定: `{pattern}` → `{agent_id}`"


@register_command(name="bindings", description="查看当前路由绑定", usage="/bindings")
async def cmd_bindings(context: CommandContext, args: list[str]) -> str:
    """列出所有路由绑定。"""
    table = context.routing_table
    if table is None:
        return "路由表不可用（需 Server 模式）"
    bindings = table.get_bindings()
    if not bindings:
        return "暂无路由绑定，所有消息走默认 Agent。"
    lines = ["当前路由绑定（按优先级）:"]
    for b in bindings:
        tier_name = {0: "精确", 1: "正则", 2: "通配"}.get(b.tier, str(b.tier))
        lines.append(f"  [{tier_name}] {b.value} → {b.agent}")
    return "\n".join(lines)


@register_command(name="agents", description="查看可用 Agent", usage="/agents")
async def cmd_agents(context: CommandContext, args: list[str]) -> str:
    """列出所有可用 Agent。"""
    agent = context.session.agent
    loader = agent.agent_def.__class__.__name__  # 需要 AgentLoader
    # 通过 session agent 的 history 路径反推 agents_dir
    from pathlib import Path
    from ..agent_loader import AgentLoader

    history_path = getattr(agent.history_manager, 'sessions_dir', Path("workspace/sessions"))
    agents_dir = history_path.parent / "agents"
    if not agents_dir.exists():
        agents_dir = Path("workspace/agents")

    loader = AgentLoader(agents_dir)
    agents = loader.discover_agents()
    current_id = agent.agent_def.id or agent.agent_def.name

    lines = ["可用 Agent:"]
    for a in agents:
        mark = " (当前)" if (a.id or a.name) == current_id else ""
        lines.append(f"  • `{a.id or a.name}`{mark} - {a.description}")
    return "\n".join(lines)