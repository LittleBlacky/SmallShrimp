"""SerpAPI search provider - unified API for multiple search engines."""
import httpx


class SerpAPISearchProvider:
    """
    SerpAPI 搜索 Provider。
    一个 API key 支持 Google、Bing、DuckDuckGo 等多个搜索引擎。
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.api_url = "https://serpapi.com/search"
        self.client = httpx.AsyncClient(timeout=30.0)

    async def search(self, query: str) -> list:
        """执行 SerpAPI 搜索。"""
        from ..web_search import SearchResult

        try:
            response = await self.client.get(
                self.api_url,
                params={
                    "q": query,
                    "api_key": self.api_key,
                    "engine": "google",  # 默认使用 Google
                    "num": 10
                }
            )
            response.raise_for_status()

            data = response.json()
            return self._parse_results(data)

        except Exception:
            raise

    def _parse_results(self, data: dict) -> list:
        """解析 SerpAPI 响应。"""
        from ..web_search import SearchResult

        results = []
        organic_results = data.get("organic_results", [])

        for item in organic_results:
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", "")
            ))

        return results

    async def close(self):
        """关闭客户端。"""
        await self.client.aclose()