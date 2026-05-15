"""Web search provider interface and factory."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)


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


def create_web_search_providers(config: dict) -> list[WebSearchProvider]:
    """
    根据配置创建搜索提供商列表（按优先级排序）。
    创建时做格式检查，无效的跳过。
    """
    providers = []

    # Priority 1: 自定义配置
    if config.get("custom", {}).get("enabled"):
        provider = _create_custom_provider(config["custom"])
        if provider:
            providers.append(provider)
            logger.info("WebSearch: custom provider loaded")

    # Priority 2: 预置 Provider
    provider_name = config.get("provider", {}).get("name")
    if provider_name:
        provider = _create_builtin_provider(
            provider_name,
            config.get("provider", {}).get("api_key", "")
        )
        if provider:
            providers.append(provider)
            logger.info(f"WebSearch: {provider_name} provider loaded")

    # Priority 3: 默认兜底 (DuckDuckGo 免费搜索)
    # 只有当 Priority 1 和 Priority 2 都为空时才添加
    if not providers:
        default = "duckduckgo"
        default_provider = _create_builtin_provider(default, "")
        if default_provider:
            providers.append(default_provider)
            logger.info(f"WebSearch: default provider ({default}) loaded")

    return providers


def _create_custom_provider(custom_config: dict) -> Optional[WebSearchProvider]:
    """创建自定义 Provider，做格式检查。"""
    from .generic import GenericSearchProvider

    provider = GenericSearchProvider(custom_config)

    if not provider.is_valid():
        logger.warning("WebSearch: custom provider config is invalid, skipping")
        return None

    return provider


def _create_builtin_provider(name: str, api_key: str) -> Optional[WebSearchProvider]:
    """创建预置 Provider。"""
    providers = {
        "serpapi": ("serpapi", "SerpAPISearchProvider"),
        "brave": ("brave", "BraveSearchProvider"),
        "duckduckgo": ("duckduckgo", "DuckDuckGoSearchProvider"),
    }

    provider_info = providers.get(name.lower())
    if not provider_info:
        logger.warning(f"WebSearch: unknown provider '{name}', skipping")
        return None

    class_name = provider_info[1]

    try:
        if class_name == "SerpAPISearchProvider":
            from .serpapi import SerpAPISearchProvider
            return SerpAPISearchProvider(api_key=api_key) if api_key else None
        elif class_name == "BraveSearchProvider":
            from .brave import BraveSearchProvider
            return BraveSearchProvider(api_key=api_key) if api_key else None
        elif class_name == "DuckDuckGoSearchProvider":
            from .duckduckgo import DuckDuckGoSearchProvider
            return DuckDuckGoSearchProvider()
    except Exception as e:
        logger.warning(f"WebSearch: failed to create {name} provider: {e}")
        return None

    return None