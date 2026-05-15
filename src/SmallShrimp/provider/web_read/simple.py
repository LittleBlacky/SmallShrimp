"""Simple HTTP web read provider."""
import httpx
import re


class SimpleWebReadProvider:
    """简单网页读取提供商，使用 httpx。"""

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    async def read(self, url: str):
        """读取网页内容。"""
        try:
            response = await self.client.get(url)
            response.raise_for_status()

            text = response.text

            # 提取标题
            title = ""
            if "<title" in text:
                start = text.find("<title") + 7
                end = text.find("</title>", start)
                if end > start:
                    title = text[start:end].strip()

            # 移除 HTML 标签获取纯文本
            clean_text = re.sub(r'<[^>]+>', ' ', text)
            clean_text = re.sub(r'\s+', ' ', clean_text).strip()

            # 限制内容长度
            content = clean_text[:10000]

            return {
                "url": url,
                "title": title,
                "content": content,
                "error": None,
            }

        except Exception as e:
            return {
                "url": url,
                "title": "",
                "content": "",
                "error": str(e),
            }

    async def close(self):
        await self.client.aclose()