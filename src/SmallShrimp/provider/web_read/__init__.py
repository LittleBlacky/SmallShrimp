"""Web read provider interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ReadResult:
    """网页读取结果。"""
    url: str
    title: str
    content: str
    error: str | None = None


class WebReadProvider(ABC):
    """网页阅读提供商基类。"""

    @abstractmethod
    async def read(self, url: str) -> ReadResult:
        """读取网页内容。"""
        pass


def create_web_read_provider(config: dict | None = None) -> WebReadProvider:
    """根据配置创建阅读提供商。"""
    from .simple import SimpleWebReadProvider
    return SimpleWebReadProvider()