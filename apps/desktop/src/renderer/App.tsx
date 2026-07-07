import {useState, useEffect, useRef} from "react";
import type {ServerState} from "@shared/types";
import {ChatWebSocket} from "./services/ws";
import {useChatStore} from "./stores/chatStore";
import {useServerStore} from "./stores/serverStore";
import {ChatView} from "./components/chat/ChatView";

function App() {
  const serverStatus = useServerStore((s) => s.status);
  const serverPort = useServerStore((s) => s.port);
  const currentAgent = useServerStore((s) => s.currentAgent);
  const setStatus = useServerStore((s) => s.setStatus);
  const setAgent = useServerStore((s) => s.setAgent);
  const handleWsEvent = useChatStore((s) => s.handleWsEvent);
  const clearMessages = useChatStore((s) => s.clearMessages);
  const currentSessionId = useChatStore((s) => s.currentSessionId);
  const setSessionId = useChatStore((s) => s.setSessionId);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<ChatWebSocket | null>(null);

  // 监听 Main Process 推送的状态
  useEffect(() => {
    if (!window.electronAPI) {
      console.warn("electronAPI 不可用（浏览器开发模式）");
      return;
    }
    window.electronAPI.onServerStatusChange((state) => {
      setStatus(state.status, state.port);
    });
    window.electronAPI.getServerStatus().then((state) => {
      setStatus(state.status, state.port);
    });
  }, [setStatus]);

  // Server 就绪时自动连接 WebSocket
  useEffect(() => {
    if (serverStatus === "running" && serverPort > 0) {
      wsRef.current = new ChatWebSocket(handleWsEvent);
      wsRef.current.connect(serverPort, currentAgent);
      return () => {
        wsRef.current?.disconnect();
      };
    }
  }, [serverStatus, serverPort, currentAgent, handleWsEvent]);

  const handleStart = async () => {
    if (!window.electronAPI) {
      setError("electronAPI 不可用（请在 Electron 中运行）");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setStatus("starting");
      const {port} = await window.electronAPI.startServer();
      setStatus("running", port);
    } catch (err: any) {
      setError(err.message || "启动失败");
      setStatus("error");
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    wsRef.current?.disconnect();
    if (window.electronAPI) {
      await window.electronAPI.stopServer();
    }
    setStatus("stopped");
  };

  const handleSend = (content: string) => {
    wsRef.current?.send(content);
  };

  // ─── 启动页面（Server 未运行） ──────────────────────
  if (serverStatus !== "running") {
    const statusColor = {
      stopped: "bg-gray-400",
      starting: "bg-yellow-400",
      running: "bg-green-500",
      error: "bg-red-500",
    }[serverStatus];

    const statusText = {
      stopped: "未启动",
      starting: "启动中...",
      running: "运行中",
      error: "异常",
    }[serverStatus];

    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-6 p-8">
        <h1 className="text-2xl font-bold">🦐 SmallShrimp Desktop</h1>

        <div className="flex items-center gap-3">
          <span className={`w-3 h-3 rounded-full ${statusColor}`} />
          <span className="text-lg">{statusText}</span>
          {serverPort > 0 && (
            <span className="text-sm text-muted-foreground">:{serverPort}</span>
          )}
        </div>

        <div className="flex gap-3">
          {serverStatus === "stopped" || serverStatus === "error" ? (
            <button
              onClick={handleStart}
              disabled={loading}
              className="px-6 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50"
            >
              {loading ? "启动中..." : "启动服务"}
            </button>
          ) : (
            <button
              onClick={handleStop}
              className="px-6 py-2 bg-red-600 text-white rounded-md hover:bg-red-700"
            >
              停止服务
            </button>
          )}
        </div>

        {error && (
          <div className="px-4 py-2 bg-red-50 border border-red-200 rounded-md text-red-700 text-sm">
            {error}
          </div>
        )}
      </div>
    );
  }

  // ─── 聊天页面（Server 运行中） ──────────────────────
  return (
    <div className="flex flex-col h-screen">
      {/* 顶部栏 */}
      <header className="flex items-center justify-between px-4 py-2 border-b bg-white dark:bg-gray-900 titlebar-drag">
        <div className="flex items-center gap-2 titlebar-no-drag">
          <span className="w-2 h-2 rounded-full bg-green-500" />
          <span className="text-sm font-medium">SmallShrimp</span>
          <span className="text-xs text-muted-foreground">:{serverPort}</span>
        </div>
        <div className="flex items-center gap-2 titlebar-no-drag">
          <select
            value={currentAgent}
            onChange={(e) => setAgent(e.target.value)}
            className="text-sm border rounded px-2 py-1"
          >
            <option value="pickle">pickle</option>
          </select>
          <button
            onClick={handleStop}
            className="text-xs text-red-600 hover:text-red-800"
          >
            停止
          </button>
        </div>
      </header>

      {/* 聊天区 */}
      <main className="flex-1 overflow-hidden">
        <ChatView onSend={handleSend} />
      </main>
    </div>
  );
}

export default App;
