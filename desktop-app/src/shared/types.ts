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

declare global {
  interface Window {
    electronAPI: ElectronAPI;
  }
}
