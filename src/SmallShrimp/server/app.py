from __future__ import annotations
"""FastAPI 应用，支持 WebSocket。"""
from fastapi import FastAPI, WebSocket
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

        if not hasattr(context, "websocket_worker") or context.websocket_worker is None:
            await websocket.close(code=1013, reason="WebSocket 不可用")
            return

        await context.websocket_worker.handle_connection(websocket)

    @app.get("/health")
    async def health_check():
        """健康检查端点。"""
        return {"status": "ok", "clients": len(context.websocket_worker.clients) if hasattr(context, "websocket_worker") else 0}

    return app