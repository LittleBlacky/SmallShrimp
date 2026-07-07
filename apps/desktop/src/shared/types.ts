// Main ↔ Renderer 共享类型

export type ServerStatus = "stopped" | "starting" | "running" | "error";

export interface ServerState {
  status: ServerStatus;
  port: number;
  error?: string;
}

export interface ElectronAPI {
  startServer: () => Promise<{port: number}>;
  stopServer: () => Promise<{success: boolean}>;
  getServerStatus: () => Promise<ServerState>;
  readFile: (path: string) => Promise<string>;
  writeFile: (path: string, content: string) => Promise<{success: boolean}>;
  getAppVersion: () => Promise<string>;
  minimizeToTray: () => Promise<void>;
  onServerStatusChange: (cb: (state: ServerState) => void) => void;
}

// ─── 聊天类型 ──────────────────────────────────────────────

export type MessageStatus = "user" | "streaming" | "done" | "error";
export type WsEventType =
  | "session_created"
  | "text_delta"
  | "text_done"
  | "tool_call"
  | "tool_result"
  | "error";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: MessageStatus;
  toolCalls?: ToolCall[];
}

export interface ToolCall {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  result?: string;
  status: "running" | "done" | "error";
}

export interface SessionMeta {
  id: string;
  title: string;
  agent: string;
  created_at: number;
  last_active_at: number;
}

export interface WsEvent {
  type: WsEventType;
  [key: string]: unknown;
}

declare global {
  interface Window {
    electronAPI: ElectronAPI;
  }
}
