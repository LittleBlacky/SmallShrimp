import {useState, useEffect} from "react";
import type {ServerState} from "@shared/types";

function App() {
  const [serverState, setServerState] = useState<ServerState>({
    status: "stopped",
    port: 0,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // 监听 Main Process 推送的状态变更
    window.electronAPI.onServerStatusChange(setServerState);
    // 启动时查询当前状态
    window.electronAPI.getServerStatus().then(setServerState);
  }, []);

  const handleStart = async () => {
    setLoading(true);
    setError(null);
    try {
      const {port} = await window.electronAPI.startServer();
      setServerState({status: "running", port});
    } catch (err: any) {
      setError(err.message || "启动失败");
      setServerState({status: "error", port: 0, error: err.message});
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    await window.electronAPI.stopServer();
    setServerState({status: "stopped", port: 0});
  };

  const statusColor = {
    stopped: "bg-gray-400",
    starting: "bg-yellow-400",
    running: "bg-green-500",
    error: "bg-red-500",
  }[serverState.status];

  const statusText = {
    stopped: "未启动",
    starting: "启动中...",
    running: "运行中",
    error: "异常",
  }[serverState.status];

  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-6 p-8">
      <h1 className="text-2xl font-bold">🦐 SmallShrimp Desktop</h1>

      {/* 状态指示器 */}
      <div className="flex items-center gap-3">
        <span className={`w-3 h-3 rounded-full ${statusColor}`} />
        <span className="text-lg">{statusText}</span>
        {serverState.port > 0 && (
          <span className="text-sm text-muted-foreground">
            :{serverState.port}
          </span>
        )}
      </div>

      {/* 控制按钮 */}
      <div className="flex gap-3">
        {serverState.status === "stopped" || serverState.status === "error" ? (
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

      <p className="text-sm text-muted-foreground mt-8">
        SmallShrimp Desktop v0.1.0 — Electron 脚手架已就绪
      </p>
    </div>
  );
}

export default App;
