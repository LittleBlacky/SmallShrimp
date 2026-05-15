"""Generic search provider - configuration-driven."""
from dataclasses import dataclass
from typing import Optional
import httpx


@dataclass
class GenericSearchConfig:
    """通用搜索配置。"""
    api_url: str
    method: str = "GET"
    headers: dict = None
    params: dict = None
    results_path: str = ""
    field_mapping: dict = None

    def __post_init__(self):
        if self.headers is None:
            self.headers = {}
        if self.params is None:
            self.params = {}
        if self.field_mapping is None:
            self.field_mapping = {"title": "title", "url": "url", "snippet": "snippet"}


class GenericSearchProvider:
    """
    配置驱动的通用搜索 Provider。

    用户可以通过配置指定：
    - API URL
    - HTTP 方法
    - 请求头、参数
    - 响应结果路径
    - 字段映射
    """

    def __init__(self, config: dict):
        self.config = GenericSearchConfig(
            api_url=config.get("api_url", ""),
            method=config.get("method", "GET").upper(),
            headers=config.get("headers", {}),
            params=config.get("params", {}),
            results_path=config.get("results_path", ""),
            field_mapping=config.get("field_mapping", {
                "title": "title",
                "url": "url",
                "snippet": "snippet"
            })
        )
        self.client = httpx.AsyncClient(timeout=30.0)

    def is_valid(self) -> bool:
        """创建时检查：配置格式是否正确。"""
        if not self.config.api_url:
            return False
        if not self.config.api_url.startswith(("http://", "https://")):
            return False
        if not self.config.field_mapping:
            return False
        return True

    async def search(self, query: str) -> list:
        """执行搜索。"""
        from ..web_search import SearchResult

        # 构建请求
        headers = self._build_headers(query)
        params = self._build_params(query)

        try:
            if self.config.method == "GET":
                response = await self.client.get(
                    self.config.api_url,
                    headers=headers,
                    params=params
                )
            else:
                response = await self.client.post(
                    self.config.api_url,
                    headers=headers,
                    params=params
                )

            response.raise_for_status()
            data = response.json()

            # 解析结果
            results = self._parse_results(data)
            return results

        except Exception:
            raise

    def _build_headers(self, query: str) -> dict:
        """构建请求头，处理占位符。"""
        headers = {}
        for key, value in self.config.headers.items():
            headers[key] = self._replace_placeholders(value, query)
        return headers

    def _build_params(self, query: str) -> dict:
        """构建请求参数，处理占位符。"""
        params = {}
        for key, value in self.config.params.items():
            params[key] = self._replace_placeholders(value, query)
        return params

    def _replace_placeholders(self, text: str, query: str) -> str:
        """替换占位符。"""
        return text.replace("{query}", query)

    def _parse_results(self, data: dict) -> list:
        """解析响应数据。"""
        from ..web_search import SearchResult

        # 按路径获取结果数组
        results = data
        if self.config.results_path:
            for key in self.config.results_path.split("."):
                results = results.get(key, [])

        if not isinstance(results, list):
            results = []

        # 映射字段
        mapped = []
        for item in results:
            title_key = self.config.field_mapping.get("title", "title")
            url_key = self.config.field_mapping.get("url", "url")
            snippet_key = self.config.field_mapping.get("snippet", "snippet")

            mapped.append(SearchResult(
                title=item.get(title_key, ""),
                url=item.get(url_key, ""),
                snippet=item.get(snippet_key, "")
            ))

        return mapped

    async def close(self):
        """关闭客户端。"""
        await self.client.aclose()