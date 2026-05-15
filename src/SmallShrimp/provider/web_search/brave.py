"""Brave Search provider implementation."""
import aiohttp


class BraveSearchProvider:
    """Brave Search API provider."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.search.brave.com/res/v1/web/search"

    async def search(self, query: str) -> list:
        """执行 Brave 搜索。"""
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key,
        }
        params = {"q": query, "count": 10}

        async with aiohttp.ClientSession() as session:
            async with session.get(
                self.base_url, headers=headers, params=params
            ) as response:
                if response.status != 200:
                    return []

                data = await response.json()
                results = []

                web_results = data.get("web", {}).get("results", [])
                for item in web_results:
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("description", ""),
                    })

                return results