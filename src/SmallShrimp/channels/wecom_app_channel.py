"""企业微信应用 Channel — 双向通信。"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import socket
import struct
import time
from dataclasses import dataclass
from typing import Callable, Awaitable

import aiohttp
from Crypto.Cipher import AES

from ..core.events import EventSource
from .base import Channel

logger = logging.getLogger(__name__)


@dataclass
class WeComAppEventSource(EventSource):
    """企业微信应用来源。"""

    _namespace = "platform-wecom"
    user_id: str = ""
    corp_id: str = ""

    def __str__(self) -> str:
        return f"platform-wecom:{self.user_id}"

    @classmethod
    def from_string(cls, s: str) -> "WeComAppEventSource":
        _, user_id = s.split(":", 1)
        return cls(user_id=user_id)

    @property
    def platform_name(self) -> str:
        return "wecom"


class _WXBizMsgCrypt:
    """企业微信消息加解密。"""

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        self.token = token
        self.aes_key = base64.b64decode(encoding_aes_key + "=")
        self.corp_id = corp_id

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        """验证回调 URL，解密 echostr。"""
        signature = self._signature(timestamp, nonce, echostr)
        if signature != msg_signature:
            raise ValueError("签名不匹配")
        return self._decrypt(echostr)

    def decrypt_msg(self, msg_signature: str, timestamp: str, nonce: str, encrypt_body: str) -> dict:
        """解密消息。"""
        signature = self._signature(timestamp, nonce, encrypt_body)
        if signature != msg_signature:
            raise ValueError("签名不匹配")
        xml = self._decrypt(encrypt_body)
        return self._parse_xml(xml)

    def _signature(self, timestamp: str, nonce: str, encrypt: str) -> str:
        raw = "".join(sorted([self.token, timestamp, nonce, encrypt]))
        return hashlib.sha1(raw.encode()).hexdigest()

    def _decrypt(self, encrypted: str) -> str:
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16])
        plain = cipher.decrypt(base64.b64decode(encrypted))
        # 去掉 padding
        pad = plain[-1]
        plain = plain[:-pad]
        # 去掉前 16 字节随机数 + 4 字节长度
        content = plain[16:]
        length = struct.unpack(">I", content[:4])[0]
        content = content[4:4 + length]
        return content.decode("utf-8")

    @staticmethod
    def _parse_xml(xml: str) -> dict:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml)
        return {
            "ToUserName": root.find("ToUserName").text or "",
            "FromUserName": root.find("FromUserName").text or "",
            "CreateTime": root.find("CreateTime").text or "",
            "MsgType": root.find("MsgType").text or "",
            "Content": root.find("Content").text or "",
            "MsgId": root.find("MsgId").text or "",
        }


class WeComAppChannel(Channel[WeComAppEventSource]):
    """企业微信应用 Channel — 双向。

    需要公网回调 URL：https://your-domain/wecom/callback
    """

    platform_name = "wecom"

    def __init__(self, config: "WeComAppConfig"):
        self.config = config
        self._session: aiohttp.ClientSession | None = None
        self._access_token: str = ""
        self._token_expires: float = 0
        self._crypto = _WXBizMsgCrypt(config.token, config.encoding_aes_key, config.corp_id)
        self._on_message: Callable | None = None
        self._stop_event = asyncio.Event()

    def is_allowed(self, source: WeComAppEventSource) -> bool:
        return True

    async def run(self, on_message: Callable[[str, WeComAppEventSource], Awaitable[None]]) -> None:
        self._on_message = on_message
        await self._stop_event.wait()

    async def reply(self, content: str, source: WeComAppEventSource) -> None:
        """发送消息给用户。"""
        token = await self._get_access_token()
        if not token or not self._session:
            return

        payload = {
            "touser": source.user_id,
            "msgtype": "text",
            "agentid": self.config.agent_id,
            "text": {"content": content},
        }
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
        try:
            async with self._session.post(url, json=payload) as resp:
                if resp.status != 200:
                    logger.error(f"发送消息失败: {resp.status}")
        except Exception as e:
            logger.error(f"发送消息异常: {e}")

    async def _get_access_token(self) -> str:
        """获取/刷新 access_token。"""
        if self._access_token and time.time() < self._token_expires:
            return self._access_token

        if not self._session:
            self._session = aiohttp.ClientSession()

        url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={self.config.corp_id}&corpsecret={self.config.secret}"
        async with self._session.get(url) as resp:
            data = await resp.json()
            if data.get("errcode") == 0:
                self._access_token = data["access_token"]
                self._token_expires = time.time() + data["expires_in"] - 300
                return self._access_token

        logger.error(f"获取 access_token 失败: {data}")
        return ""

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        """验证回调 URL（GET 请求）。"""
        return self._crypto.verify_url(msg_signature, timestamp, nonce, echostr)

    def handle_callback(self, msg_signature: str, timestamp: str, nonce: str, body: str) -> dict | None:
        """处理回调消息（POST 请求），解密并返回结构化数据。"""
        try:
            return self._crypto.decrypt_msg(msg_signature, timestamp, nonce, body)
        except Exception as e:
            logger.error(f"解密消息失败: {e}")
            return None

    async def stop(self) -> None:
        self._stop_event.set()
        if self._session:
            await self._session.close()
            self._session = None
