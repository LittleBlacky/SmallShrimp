"""命令基类。"""
from dataclasses import dataclass
from typing import Callable, Awaitable


@dataclass
class AgentTask:
    """命令需要继续交给当前 Agent 执行的任务。"""
    prompt: str


@dataclass
class Command:
    """命令定义。"""
    name: str
    description: str
    usage: str  # 例如 "/skill <name>"
    handler: "CommandHandler"

CommandResult = str | AgentTask
CommandHandler = Callable[["CommandContext", list[str]], Awaitable[CommandResult]]


async def resolve_command_result(session, result: CommandResult) -> str:
    """把命令结果解析为可发送给用户的文本响应。"""
    if isinstance(result, AgentTask):
        return await session.chat(result.prompt)
    return result
