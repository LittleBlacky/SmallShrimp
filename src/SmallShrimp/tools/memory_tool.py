"""Memory tools — 分层记忆检索与存储。"""
from ..tools.decorators import tool


def create_memory_tools(memory_manager):
    """创建分层记忆工具集。"""
    tools: list = []

    @tool(description="搜索任务相关长期记忆。默认只查 facts/projects/reflections，不查用户画像；用户画像已由系统提示稳定注入。")
    async def recall_memory(query: str) -> str:
        records = memory_manager.recall(query, limit=5)
        if not records:
            return "未找到相关任务记忆。"
        return "\n".join(f"- [{r['layer']}] {r['content']}" for r in records)

    tools.append(recall_memory)

    @tool(description="保存稳定用户画像，例如姓名、长期偏好、沟通语言、用户明确纠正。不要保存临时任务状态。")
    async def remember_profile(content: str) -> str:
        record = memory_manager.remember_profile(content)
        return f"已保存用户画像: {record['content']}"

    tools.append(remember_profile)

    @tool(description="保存普通事实记忆，用于跨会话召回；不进入用户画像 prompt。")
    async def remember_fact(content: str, importance: int = 5) -> str:
        record = memory_manager.remember_fact(content, importance=importance)
        return f"已保存事实记忆: {record['content']}"

    tools.append(remember_fact)

    @tool(description="保存当前项目/仓库相关记忆，例如路径、命令、技术栈、约定。")
    async def remember_project(content: str, importance: int = 6) -> str:
        record = memory_manager.remember_project(content, importance=importance)
        return f"已保存项目记忆: {record['content']}"

    tools.append(remember_project)

    @tool(description="保存 agent 反思记忆，例如失败模式、用户纠正后的经验、工具使用教训。")
    async def remember_reflection(content: str, importance: int = 6) -> str:
        record = memory_manager.remember_reflection(content, importance=importance)
        return f"已保存反思记忆: {record['content']}"

    tools.append(remember_reflection)

    @tool(description="扫描并合并 facts/projects/reflections/sessions 中的相似记录；不会合并用户画像。")
    async def consolidate_memories(threshold: float = 0.8) -> str:
        count = memory_manager.consolidate(threshold=threshold)
        return f"合并了 {count} 对相似记忆。" if count else "没有找到可合并的记忆。"

    tools.append(consolidate_memories)

    return tools
