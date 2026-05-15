"""DuckDuckGo search provider - no API key required."""
import httpx


class DuckDuckGoSearchProvider:
    """DuckDuckGo HTML 搜索 Provider，无需 API Key。"""

    def __init__(self, api_key: str = ""):
        self.api_url = "https://html.duckduckgo.com/html/"
        self.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    async def search(self, query: str) -> list:
        """执行 DuckDuckGo 搜索。"""
        from ..web_search import SearchResult

        try:
            # 先获取搜索页面，提取 URL
            response = await self.client.get(
                self.api_url,
                params={"q": query}
            )
            response.raise_for_status()

            # 解析 HTML 获取结果
            results = self._parse_html(response.text)
            return results

        except Exception:
            raise

    def _parse_html(self, html: str) -> list:
        """简单解析 DuckDuckGo HTML 结果。"""
        from ..web_search import SearchResult

        results = []

        # 检测是否是挑战页面（被反爬）
        if "<title>DuckDuckGo</title>" in html and "result__a" not in html:
            # 返回空结果，让系统降级到下一个 Provider
            return results

        # 简单的正则匹配
        import re

        # 匹配结果: <a class="result__a" href="...">Title</a>
        pattern = r'<a class="result__a" href="([^"]+)">([^<]+)</a>'
        matches = re.findall(pattern, html)

        # 匹配 snippet: <a class="result__snippet" ...>Snippet</a>
        snippet_pattern = r'<a class="result__snippet"[^>]*>([^<]+)</a>'
        snippets = re.findall(snippet_pattern, html)

        for i, (url, title) in enumerate(matches[:10]):
            snippet = snippets[i] if i < len(snippets) else ""
            results.append(SearchResult(
                title=title.strip(),
                url=url.strip(),
                snippet=snippet.strip()
            ))

        return results

    async def close(self):
        """关闭客户端。"""
        await self.client.aclose()