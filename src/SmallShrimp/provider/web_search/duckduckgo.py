"""DuckDuckGo search provider using ddgs package."""
from ddgs import DDGS
from ..web_search import SearchResult


class DuckDuckGoSearchProvider:
    """DuckDuckGo HTML 搜索 Provider，无需 API Key。"""

    def __init__(self, api_key: str = ""):
        self._client: DDGS | None = None

    def _get_client(self) -> DDGS:
        if self._client is None:
            self._client = DDGS()
        return self._client

    async def search(self, query: str) -> list:
        """执行 DuckDuckGo 搜索。"""
        try:
            client = self._get_client()
            results = list(client.text(query, max_results=10))
            return [
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("href", ""),
                    snippet=r.get("body", "")
                )
                for r in results
                if r.get("href")
            ]
        except Exception:
            raise

    async def close(self):
        """关闭客户端。"""
        if self._client:
            self._client = None