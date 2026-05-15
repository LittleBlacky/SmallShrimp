"""Web search provider interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SearchResult:
    """搜索结果。"""
    title: str
    url: str
    snippet: str


class WebSearchProvider(ABC):
    """网络搜索提供商基类。"""

    @abstractmethod
    async def search(self, query: str) -> list[SearchResult]:
        """执行搜索，返回结果列表。"""
        pass


def create_web_search_provider(config: dict) -> WebSearchProvider | None:
    """根据配置创建搜索提供商。"""
    provider = config.get("provider", "brave")
    if provider == "brave":
        from .brave import BraveSearchProvider
        api_key = config.get("api_key", "")
        if api_key:
            return BraveSearchProvider(api_key=api_key)
    return None