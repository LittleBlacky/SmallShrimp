"""企业微信 Channel 测试。"""
import struct
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── 群机器人 Channel ──

def test_wecom_channel_creation():
    """WeComChannel 可以创建。"""
    from src.SmallShrimp.channels.wecom_channel import WeComChannel
    ch = WeComChannel("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test")
    assert ch.platform_name == "wecom"


@pytest.mark.asyncio
async def test_wecom_channel_reply():
    """reply 发送正确格式的 JSON。"""
    import json
    from unittest.mock import AsyncMock, patch
    from src.SmallShrimp.channels.wecom_channel import WeComChannel, WeComEventSource

    ch = WeComChannel("https://example.com/webhook")
    source = WeComEventSource(webhook_key="test")

    mock_resp = AsyncMock()
    mock_resp.status = 200

    mock_session = AsyncMock()
    mock_session.post = MagicMock()
    mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    ch._session = mock_session

    await ch.reply("你好", source)

    # 验证发送的 JSON 格式
    call_args = mock_session.post.call_args
    assert call_args[0][0] == "https://example.com/webhook"
    sent = call_args[1]["json"]
    assert sent["msgtype"] == "text"
    assert sent["text"]["content"] == "你好"


# ── 应用 Channel 加解密 ──

def test_wxbizmsgcrypt_signature():
    """签名计算正确。"""
    from src.SmallShrimp.channels.wecom_app_channel import _WXBizMsgCrypt

    crypto = _WXBizMsgCrypt(
        token="test_token",
        encoding_aes_key="abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG",
        corp_id="test_corp",
    )
    sig = crypto._signature("1234567890", "nonce123", "encrypt_body")
    # 签名应为 40 字符的 hex
    assert len(sig) == 40


def test_wxbizmsgcrypt_decrypt():
    """解密正常。"""
    import base64
    from Crypto.Cipher import AES
    from src.SmallShrimp.channels.wecom_app_channel import _WXBizMsgCrypt

    aes_key = base64.b64decode("abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG" + "=")
    corp_id = "test_corp"
    crypto = _WXBizMsgCrypt(
        token="token",
        encoding_aes_key="abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG",
        corp_id=corp_id,
    )

    # 构造加密内容：16字节随机 + 4字节长度 + XML + corp_id
    xml = "<xml><ToUserName>a</ToUserName><FromUserName>u</FromUserName><CreateTime>0</CreateTime><MsgType>text</MsgType><Content>hi</Content><MsgId>1</MsgId></xml>"
    xml_bytes = xml.encode("utf-8")
    plain = b"\x01" * 16 + struct.pack(">I", len(xml_bytes)) + xml_bytes + corp_id.encode()
    pad = 32 - len(plain) % 32
    plain += bytes([pad]) * pad

    cipher = AES.new(aes_key, AES.MODE_CBC, aes_key[:16])
    encrypted = base64.b64encode(cipher.encrypt(plain)).decode()

    sig = crypto._signature("123", "nonce", encrypted)
    result = crypto.decrypt_msg(sig, "123", "nonce", encrypted)
    assert result["Content"] == "hi"


def test_wxbizmsgcrypt_parse_xml():
    """XML 解析正确。"""
    from src.SmallShrimp.channels.wecom_app_channel import _WXBizMsgCrypt

    crypto = _WXBizMsgCrypt("t", "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG", "c")
    xml = """<xml><ToUserName>agent</ToUserName><FromUserName>user123</FromUserName><CreateTime>123</CreateTime><MsgType>text</MsgType><Content>hello</Content><MsgId>1</MsgId></xml>"""
    result = crypto._parse_xml(xml)
    assert result["FromUserName"] == "user123"
    assert result["Content"] == "hello"
    assert result["MsgType"] == "text"


# ── 应用 Channel 创建 ──

def test_wecom_app_channel_creation():
    """WeComAppChannel 可以创建。"""
    from unittest.mock import MagicMock
    from src.SmallShrimp.channels.wecom_app_channel import WeComAppChannel

    config = MagicMock()
    config.corp_id = "test"
    config.agent_id = 1000002
    config.secret = "secret"
    config.token = "token"
    config.encoding_aes_key = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"

    ch = WeComAppChannel(config)
    assert ch.platform_name == "wecom"
    assert ch.config.corp_id == "test"


# ── 回调端点测试 ──

@pytest.mark.asyncio
async def test_wecom_verify_endpoint():
    """GET /wecom/callback 验证签名。"""
    from unittest.mock import MagicMock
    from fastapi.testclient import TestClient
    from src.SmallShrimp.server.app import create_app

    context = MagicMock()
    context.websocket_worker = MagicMock()
    context.websocket_worker.clients = set()
    context.channels = []  # 没有 wecom app channel

    app = create_app(context)
    client = TestClient(app)

    resp = client.get("/wecom/callback?msg_signature=xxx&timestamp=1&nonce=2&echostr=test")
    assert resp.status_code == 200
    # 没有配置 wecom app 时返回提示
    assert "not configured" in resp.text.lower()


if __name__ == "__main__":
    import asyncio
    test_wecom_channel_creation()
    asyncio.run(test_wecom_channel_reply())
    test_wxbizmsgcrypt_signature()
    test_wxbizmsgcrypt_decrypt()
    test_wxbizmsgcrypt_parse_xml()
    test_wecom_app_channel_creation()
    print("\nAll wecom tests passed!")
