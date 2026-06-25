import type {WsEvent} from "@shared/types";

type EventHandler = (event: WsEvent) => void;

export class ChatWebSocket {
  private ws: WebSocket | null = null;
  private handler: EventHandler;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 1000;
  private intentionalClose = false;

  constructor(handler: EventHandler) {
    this.handler = handler;
  }

  connect(port: number, agent: string, sessionId?: string) {
    const params = new URLSearchParams({agent});
    if (sessionId) params.set("session_id", sessionId);

    this.intentionalClose = false;
    const url = `ws://localhost:${port}/ws/chat?${params}`;
    console.log(`[WS] 连接: ${url}`);

    try {
      this.ws = new WebSocket(url);
    } catch (e) {
      console.error("[WS] 连接失败:", e);
      return;
    }

    this.ws.onopen = () => {
      console.log("[WS] 已连接");
      this.reconnectDelay = 1000;
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as WsEvent;
        this.handler(data);
      } catch (e) {
        console.error("[WS] 解析失败:", event.data, e);
      }
    };

    this.ws.onclose = () => {
      console.log("[WS] 已断开");
      if (!this.intentionalClose) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = (e) => {
      console.error("[WS] 错误:", e);
    };
  }

  send(content: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({type: "user_message", content}));
    } else {
      console.warn("[WS] 未连接，无法发送");
    }
  }

  disconnect() {
    this.intentionalClose = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }

  private scheduleReconnect() {
    this.reconnectTimer = setTimeout(() => {
      // 重连由外部触发（Server 重新就绪时）
      console.log(`[WS] 等待重连 (${this.reconnectDelay}ms)...`);
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
    }, this.reconnectDelay);
  }
}
