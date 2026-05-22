"""Memory tools — 记忆检索与存储。"""
from ..tools.decorators import tool


def create_memory_tools(memory_manager):
    """创建记忆工具集（recall + remember）。"""
    tools: list = []

    @tool(description="搜索用户的长期记忆库。当你不确定用户的偏好、习惯、之前提到的事实或背景信息时，先调用此工具查询记忆再回答。")
    async def recall_memory(query: str) -> str:
        records = memory_manager.recall(query, limit=5)
        if not records:
            return "未找到相关记忆。"
        lines = []
        for r in records:
            lines.append(f"- {r['content']}")
        return "\n".join(lines)

    tools.append(recall_memory)

    @tool(description="""保存新记忆。当了解到用户信息时调用。
pinned=True: 身份/名字/长期偏好/纠正指令（始终可见，不淘汰）。
kind:
  preference - 用户喜欢/不喜欢什么
  fact - 跨会话需要记住的事情/上下文
  reflection - 你自己总结的经验或洞察
不要保存可从当前上下文推导的临时信息。""")
    async def remember(content: str, pinned: bool = False, kind: str = "") -> str:
        record = memory_manager.remember(content, pinned=pinned, kind=kind)
        label = "[画像]" if pinned else ""
        return f"已记住{label}: {record['content']}"

    tools.append(remember)

    return tools
