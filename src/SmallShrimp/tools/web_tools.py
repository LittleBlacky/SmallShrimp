"""Web tools - 搜索和读取网页工具"""
import logging
from .decorators import tool
from ..provider.web_search import create_web_search_providers, SearchResult
from ..provider.web_read import create_web_read_provider

logger = logging.getLogger(__name__)


def create_websearch_tool(config: dict):
    """创建网络搜索工具。"""
    # 按优先级获取 Provider 列表
    providers = create_web_search_providers(config)

    @tool(description="Search the web for information. Returns top search results with titles, URLs, and snippets.")
    async def websearch(query: str) -> str:
        # 按优先级尝试各个 Provider
        for provider in providers:
            try:
                results = await provider.search(query)
                if results:
                    return _format_results(results)
            except Exception as e:
                logger.warning(f"WebSearch provider {provider.__class__.__name__} failed: {e}")
                continue

        return "Search services are unavailable. Please check your configuration."

    return websearch


def _format_results(results: list) -> str:
    """格式化搜索结果。"""
    output = []
    for i, r in enumerate(results, 1):
        title = r.title if isinstance(r, SearchResult) else r.get("title", "")
        url = r.url if isinstance(r, SearchResult) else r.get("url", "")
        snippet = r.snippet if isinstance(r, SearchResult) else r.get("snippet", "")
        output.append(f"{i}. **{title}**\n   {url}\n   {snippet}")
    return "\n\n".join(output)


def create_webread_tool():
    """创建网页读取工具。"""
    provider = create_web_read_provider()

    @tool(description="Read content from a URL. Returns the page title and main content text.")
    async def webread(url: str) -> str:
        result = await provider.read(url)

        if result.get("error"):
            return f"Error reading {url}: {result['error']}"

        output = f"**Title:** {result['title']}\n\n" if result.get("title") else ""
        output += f"**Content:**\n{result['content']}"
        return output

    return webread