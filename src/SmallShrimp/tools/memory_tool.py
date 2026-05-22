"""Memory tools — 记忆检索与存储。"""
from ..tools.decorators import tool


def create_memory_tools(memory_manager):
    """创建记忆工具集（recall + remember + remember_pinned）。"""
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

    @tool(description="保存新记忆。当你了解到用户的偏好、习惯、事实或其他值得长期记住的信息时调用。不要保存临时信息、代码细节或可从当前上下文推导的内容。")
    async def remember(content: str) -> str:
        record = memory_manager.remember(content)
        return f"已记住: {record['content']}"

    tools.append(remember)

    @tool(description="保存用户画像。用于记住用户的名字、身份、或需要始终关注的偏好。画像会在每次对话中自动可见。")
    async def remember_profile(content: str) -> str:
        record = memory_manager.remember_profile(content)
        return f"已记住 [画像]: {record['content']}"

    tools.append(remember_profile)

    return tools
