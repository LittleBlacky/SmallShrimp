from __future__ import annotations
"""FastAPI 应用，支持 WebSocket 和企业微信回调。"""
from fastapi import FastAPI, WebSocket, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from .context import Context


def create_app(context: Context) -> FastAPI:
    """创建并配置 FastAPI 应用。"""
    app = FastAPI(
        title="SmallShrimp WebSocket Server",
        description="WebSocket 服务器，用于实时与 Agent 交互",
        version="0.10.0",
    )

    # 允许 CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # WebSocket 端点
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket 端点，用于实时事件流和聊天。"""
        await websocket.accept()

        if context.websocket_worker is None:
            await websocket.close(code=1013, reason="WebSocket 不可用")
            return

        await context.websocket_worker.handle_connection(websocket)

    @app.get("/health")
    async def health_check():
        """健康检查端点。"""
        return {"status": "ok", "clients": len(context.websocket_worker.clients) if context.websocket_worker else 0}

    # 企业微信回调端点
    wecom_channel = _find_wecom_app_channel(context)

    @app.get("/wecom/callback")
    async def wecom_verify(
        msg_signature: str = Query(..., alias="msg_signature"),
        timestamp: str = Query(...),
        nonce: str = Query(...),
        echostr: str = Query(...),
    ):
        """企业微信回调 URL 验证。"""
        if not wecom_channel:
            return "wecom app not configured"
        try:
            result = wecom_channel.verify_url(msg_signature, timestamp, nonce, echostr)
            return result
        except Exception as e:
            return f"verify failed: {e}"

    @app.post("/wecom/callback")
    async def wecom_callback(
        request: Request,
        msg_signature: str = Query(..., alias="msg_signature"),
        timestamp: str = Query(...),
        nonce: str = Query(...),
    ):
        """企业微信回调消息。"""
        if not wecom_channel:
            return ""

        body = await request.body()
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(body)
            encrypt = root.find("Encrypt")
            encrypt_body = encrypt.text if encrypt is not None else ""
        except Exception:
            return ""

        msg = wecom_channel.handle_callback(msg_signature, timestamp, nonce, encrypt_body)
        if not msg:
            return ""

        if msg.get("MsgType") == "text":
            source = _make_wecom_source(msg, wecom_channel)
            # 发布 InboundEvent
            import time as _time
            from ..core.events import InboundEvent
            session_id = _get_session_id(context, source)
            event = InboundEvent(
                session_id=session_id,
                source=source,
                content=msg["Content"],
                timestamp=_time.time(),
            )
            await context.eventbus.publish(event)

        return ""

    return app


def _find_wecom_app_channel(context):
    """从 context 查找 WeComAppChannel。"""
    from ..channels.wecom_app_channel import WeComAppChannel
    for ch in getattr(context, "channels", []):
        if isinstance(ch, WeComAppChannel):
            return ch
    return None


def _make_wecom_source(msg: dict, channel):
    """构造 WeComAppEventSource。"""
    from ..channels.wecom_app_channel import WeComAppEventSource
    return WeComAppEventSource(
        user_id=msg.get("FromUserName", ""),
        corp_id=channel.config.corp_id,
    )


def _get_session_id(context, source):
    """获取或创建会话 ID。"""
    if context.routing_table:
        return context.routing_table.get_or_create_session_id(source)
    import uuid
    return str(uuid.uuid4())[:8]