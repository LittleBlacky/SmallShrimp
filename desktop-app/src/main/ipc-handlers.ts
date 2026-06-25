import {ipcMain, BrowserWindow, app} from "electron";
import fs from "fs";
import {
  IPC_START_SERVER,
  IPC_STOP_SERVER,
  IPC_GET_SERVER_STATUS,
  IPC_READ_FILE,
  IPC_WRITE_FILE,
  IPC_GET_APP_VERSION,
  IPC_MINIMIZE_TO_TRAY,
  IPC_SERVER_STATUS,
} from "../shared/ipc-channels";
import {startServer, stopServer, getStatus, getPort} from "./python";
import {updateTrayStatus, setMainWindow} from "./tray";

export function registerIpcHandlers() {
  // Python 进程控制
  ipcMain.handle(IPC_START_SERVER, async () => {
    try {
      // projectPath: 默认为当前工作目录（仓库根）
      const projectPath = process.cwd();
      const port = await startServer(projectPath);
      broadcastStatus("running", port);
      return {port};
    } catch (err) {
      broadcastStatus("error");
      throw err;
    }
  });

  ipcMain.handle(IPC_STOP_SERVER, async () => {
    stopServer();
    broadcastStatus("stopped");
    return {success: true};
  });

  ipcMain.handle(IPC_GET_SERVER_STATUS, () => ({
    status: getStatus(),
    port: getPort(),
  }));

  // 文件读写（供 Agent/配置管理使用）
  ipcMain.handle(IPC_READ_FILE, async (_, filePath: string) => {
    return fs.readFileSync(filePath, "utf-8");
  });

  ipcMain.handle(
    IPC_WRITE_FILE,
    async (_, filePath: string, content: string) => {
      fs.writeFileSync(filePath, content, "utf-8");
      return {success: true};
    },
  );

  // 窗口控制
  ipcMain.handle(IPC_MINIMIZE_TO_TRAY, (event) => {
    BrowserWindow.fromWebContents(event.sender)?.hide();
  });

  // 版本
  ipcMain.handle(IPC_GET_APP_VERSION, () => app.getVersion());
}

function broadcastStatus(status: string, port?: number) {
  const state: any = {status, port: port ?? getPort()};
  updateTrayStatus(status as any);
  BrowserWindow.getAllWindows().forEach((win) => {
    win.webContents.send(IPC_SERVER_STATUS, state);
  });
}
