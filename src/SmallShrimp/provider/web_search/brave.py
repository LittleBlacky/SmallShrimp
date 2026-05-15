"""Brave Search provider implementation."""
import httpx


class BraveSearchProvider:
    """Brave Search API provider."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.search.brave.com/res/v1/web/search"
        self.client = httpx.AsyncClient(timeout=30.0)

    async def search(self, query: str) -> list:
        """执行 Brave 搜索。"""
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key,
        }
        params = {"q": query, "count": 10}

        try:
            response = await self.client.get(
                self.base_url, headers=headers, params=params
            )
            response.raise_for_status()

            data = response.json()
            results = []

            web_results = data.get("web", {}).get("results", [])
            for item in web_results:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("description", ""),
                })

            return results
        except Exception:
            return []

    async def close(self):
        """关闭客户端，释放资源。"""
        await self.client.aclose()