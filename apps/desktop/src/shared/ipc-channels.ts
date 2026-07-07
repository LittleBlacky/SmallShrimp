// IPC 通道名常量 — Main ↔ Renderer 通信

// Renderer → Main
export const IPC_START_SERVER = "START_SERVER";
export const IPC_STOP_SERVER = "STOP_SERVER";
export const IPC_GET_SERVER_STATUS = "GET_SERVER_STATUS";
export const IPC_READ_FILE = "READ_FILE";
export const IPC_WRITE_FILE = "WRITE_FILE";
export const IPC_GET_APP_VERSION = "GET_APP_VERSION";
export const IPC_MINIMIZE_TO_TRAY = "MINIMIZE_TO_TRAY";

// Main → Renderer
export const IPC_SERVER_STATUS = "SERVER_STATUS";
export const IPC_UPDATE_AVAILABLE = "UPDATE_AVAILABLE";
