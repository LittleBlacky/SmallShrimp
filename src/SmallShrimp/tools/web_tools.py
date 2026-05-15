"""Web tools - 搜索和读取网页工具"""
from .decorators import tool
from ..provider.web_search import create_web_search_provider
from ..provider.web_read import create_web_read_provider


def create_websearch_tool(config: dict):
    """创建网络搜索工具。"""
    provider = create_web_search_provider(config)

    @tool(description="Search the web for information. Returns top search results with titles, URLs, and snippets.")
    async def websearch(query: str) -> str:
        if provider is None:
            return "Web search is not configured. Please set up websearch in config.user.yaml"

        results = await provider.search(query)
        if not results:
            return "No results found."

        output = []
        for i, r in enumerate(results, 1):
            output.append(f"{i}. **{r['title']}**\n   {r['url']}\n   {r['snippet']}")
        return "\n\n".join(output)

    return websearch


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