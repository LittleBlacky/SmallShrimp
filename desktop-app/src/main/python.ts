import {ChildProcess, spawn} from "child_process";
import path from "path";
import fs from "fs";
import http from "http";
import type {ServerStatus} from "../shared/types";

let pythonProcess: ChildProcess | null = null;
let serverPort = 0;
let autoRestart = true;

export function getStatus(): ServerStatus {
  if (!pythonProcess) return "stopped";
  if (pythonProcess.exitCode !== null) return "error";
  return "running";
}

export function getPort(): number {
  return serverPort;
}

/**
 * 查找 Python 可执行文件
 */
function findPython(projectPath: string): string {
  // 1. .venv (Windows)
  const venvWin = path.join(projectPath, ".venv", "Scripts", "python.exe");
  if (fs.existsSync(venvWin)) return venvWin;

  // 2. .venv (Unix)
  const venvUnix = path.join(projectPath, ".venv", "bin", "python");
  if (fs.existsSync(venvUnix)) return venvUnix;

  // 3. 系统 PATH
  return process.platform === "win32" ? "python" : "python3";
}

/**
 * 查找可用端口（从 8765 开始递增）
 */
function findAvailablePort(startPort = 8765): Promise<number> {
  return new Promise((resolve) => {
    const server = http.createServer();
    server.listen(startPort, () => {
      server.close(() => resolve(startPort));
    });
    server.on("error", () => {
      resolve(findAvailablePort(startPort + 1));
    });
  });
}

/**
 * 健康检查轮询
 */
function waitForHealth(port: number, timeoutMs = 30000): Promise<void> {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const check = () => {
      if (Date.now() - start > timeoutMs) {
        return reject(new Error(`Server 启动超时 (${timeoutMs}ms)`));
      }
      http
        .get(`http://localhost:${port}/health`, (res) => {
          if (res.statusCode === 200) return resolve();
          setTimeout(check, 500);
        })
        .on("error", () => {
          setTimeout(check, 500);
        });
    };
    check();
  });
}

/**
 * 启动 SmallShrimp Server
 */
export async function startServer(projectPath: string): Promise<number> {
  if (pythonProcess) {
    throw new Error("Server 已在运行中");
  }

  const pythonPath = findPython(projectPath);
  serverPort = await findAvailablePort();

  console.log(`[Python] 启动: ${pythonPath} (端口 ${serverPort})`);

  pythonProcess = spawn(
    pythonPath,
    ["-m", "SmallShrimp.server.server", "--port", String(serverPort)],
    {
      cwd: projectPath,
      stdio: ["pipe", "pipe", "pipe"],
    },
  );

  // 收集日志
  pythonProcess.stdout?.on("data", (data) => {
    console.log(`[Python] ${data.toString().trim()}`);
  });
  pythonProcess.stderr?.on("data", (data) => {
    console.error(`[Python:err] ${data.toString().trim()}`);
  });

  // 监听退出
  pythonProcess.on("exit", (code) => {
    console.log(`[Python] 进程退出 (code: ${code})`);
    pythonProcess = null;
    if (autoRestart && code !== 0) {
      console.log("[Python] 2 秒后自动重启...");
      setTimeout(() => startServer(projectPath).catch(console.error), 2000);
    }
  });

  await waitForHealth(serverPort);
  console.log(`[Python] Server 就绪: http://localhost:${serverPort}`);
  return serverPort;
}

/**
 * 停止 Server
 */
export function stopServer(): void {
  autoRestart = false;
  if (pythonProcess) {
    pythonProcess.kill("SIGTERM");
    pythonProcess = null;
  }
  autoRestart = true;
}
