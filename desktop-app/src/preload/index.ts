import {contextBridge, ipcRenderer} from "electron";
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
import type {ServerState} from "../shared/types";

contextBridge.exposeInMainWorld("electronAPI", {
  startServer: () => ipcRenderer.invoke(IPC_START_SERVER),
  stopServer: () => ipcRenderer.invoke(IPC_STOP_SERVER),
  getServerStatus: () => ipcRenderer.invoke(IPC_GET_SERVER_STATUS),
  readFile: (path: string) => ipcRenderer.invoke(IPC_READ_FILE, path),
  writeFile: (path: string, content: string) =>
    ipcRenderer.invoke(IPC_WRITE_FILE, path, content),
  getAppVersion: () => ipcRenderer.invoke(IPC_GET_APP_VERSION),
  minimizeToTray: () => ipcRenderer.invoke(IPC_MINIMIZE_TO_TRAY),
  onServerStatusChange: (cb: (state: ServerState) => void) => {
    ipcRenderer.on(IPC_SERVER_STATUS, (_, data) => cb(data));
  },
});
