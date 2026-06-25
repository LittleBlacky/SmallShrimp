import {Tray, Menu, MenuItem, nativeImage, BrowserWindow} from "electron";
import path from "path";
import type {ServerStatus} from "../shared/types";

let tray: Tray | null = null;
let mainWindow: BrowserWindow | null = null;

/**
 * 动态绘制状态圆点图标 (16x16)
 */
function createStatusIcon(status: ServerStatus): Electron.NativeImage {
  const colors: Record<ServerStatus, string> = {
    stopped: "#9ca3af",
    starting: "#facc15",
    running: "#22c55e",
    error: "#ef4444",
  };

  // 创建 16x16 纯色圆点图标
  const size = 16;
  const buffer = Buffer.alloc(size * size * 4);
  const color = colors[status];
  const r = parseInt(color.slice(1, 3), 16);
  const g = parseInt(color.slice(3, 5), 16);
  const b = parseInt(color.slice(5, 7), 16);

  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = x - 7.5,
        dy = y - 7.5;
      const dist = Math.sqrt(dx * dx + dy * dy);
      const alpha = dist <= 6 ? 255 : 0;
      const i = (y * size + x) * 4;
      buffer[i] = r;
      buffer[i + 1] = g;
      buffer[i + 2] = b;
      buffer[i + 3] = alpha;
    }
  }

  return nativeImage.createFromBuffer(buffer, {width: size, height: size});
}

export function setMainWindow(win: BrowserWindow) {
  mainWindow = win;
}

export function createTray() {
  tray = new Tray(createStatusIcon("stopped"));
  tray.setToolTip("SmallShrimp");

  tray.on("click", () => {
    mainWindow?.show();
    mainWindow?.focus();
  });

  updateMenu("stopped");
}

function updateMenu(status: ServerStatus) {
  const isRunning = status === "running";

  const menu = Menu.buildFromTemplate([
    {
      label: "SmallShrimp",
      enabled: false,
    },
    {type: "separator"},
    {
      label: "显示主窗口",
      click: () => {
        mainWindow?.show();
        mainWindow?.focus();
      },
    },
    {type: "separator"},
    {
      label: isRunning ? "停止服务" : "启动服务",
      click: () => {
        // 通过 IPC 间接调用，或直接发事件
      },
    },
    {type: "separator"},
    {
      label: "退出",
      click: () => {
        (global as any).__isQuitting = true;
        require("electron").app.quit();
      },
    },
  ]);

  tray?.setContextMenu(menu);
}

export function updateTrayStatus(status: ServerStatus) {
  tray?.setImage(createStatusIcon(status));
  updateMenu(status);
}
