import {app, BrowserWindow} from "electron";
import path from "path";
import {registerIpcHandlers} from "./ipc-handlers";
import {createTray} from "./tray";

let mainWindow: BrowserWindow | null = null;

const isDev = !app.isPackaged;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    frame: false,
    titleBarStyle: "hidden",
    webPreferences: {
      preload: path.join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // 加载页面
  if (isDev) {
    mainWindow.loadURL("http://localhost:5173");
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, "../renderer/index.html"));
  }

  // 关闭窗口 → 最小化到托盘
  mainWindow.on("close", (event) => {
    const isQuitting = (global as any).__isQuitting
    if (!isQuitting) {
      event.preventDefault();
      mainWindow?.hide();
    }
  });
}

app.whenReady().then(() => {
  registerIpcHandlers();
  createWindow();
  createTray();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("before-quit", () => {
  (app as any).isQuitting = true;
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
