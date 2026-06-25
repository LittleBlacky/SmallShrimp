# 桌面壳 — 技术架构设计

> 版本: v0.1 | 日期: 2026-06-25 | 状态: 草案
> 关联: @ref: PRD.md, @ref: ../../TECH-DESIGN.md

---

## 1. Main Process 模块设计

### 1.1 文件职责

```
src/main/
├── index.ts          # 入口：app.whenReady → 创建窗口、注册 IPC、初始化托盘
├── python.ts         # Python 子进程：spawn / health check / restart / kill
├── tray.ts           # 托盘：图标切换、右键菜单、点击事件
├── ipc-handlers.ts   # IPC 注册中心：集中 handle() 所有通道
└── updater.ts        # 自动更新 (P2)：electron-updater 集成
```

### 1.2 `index.ts` 初始化流程

```
app.whenReady()
  ├── 1. 创建 BrowserWindow
  │       ├── width: 1200, height: 800, minWidth: 800
  │       ├── frame: false (自定义标题栏)
  │       ├── webPreferences.preload
  │       └── 加载 Vite dev server 或打包后的 index.html
  │
  ├── 2. 注册 IPC Handlers (ipc-handlers.ts)
  │
  ├── 3. 初始化 Tray (tray.ts)
  │       └── 默认 stopped 状态图标
  │
  └── 4. 监听 app 事件
          ├── window-all-closed → 不退出 (macOS 惯例)
          └── before-quit → 清理 Python 子进程
```

### 1.3 窗口配置

```typescript
// index.ts
const mainWindow = new BrowserWindow({
  width: 1200,
  height: 800,
  minWidth: 800,
  minHeight: 600,
  frame: false,                    // 自定义标题栏
  titleBarStyle: 'hidden',        // macOS 隐藏标题栏但保留红绿灯
  webPreferences: {
    preload: path.join(__dirname, '../preload/index.js'),
    contextIsolation: true,        // 安全：渲染进程不直接访问 Node
    nodeIntegration: false,
  },
});
```

---

## 2. Python 进程管理 (`python.ts`)

### 2.1 状态机

```
  ┌─────────┐   spawn    ┌──────────┐  health OK  ┌─────────┐
  │ STOPPED │ ────────▶  │ STARTING │ ──────────▶ │ RUNNING │
  └─────────┘            └──────────┘             └────┬────┘
       ▲                      │                       │
       │      timeout         │           exit/error  │
       └──────────────────────┘  ◀────────────────────┘
                              │
                              ▼
                        ┌─────────┐
                        │  ERROR  │
                        └─────────┘
```

### 2.2 核心实现

```typescript
// python.ts
import { ChildProcess, spawn } from 'child_process';
import http from 'http';

let pythonProcess: ChildProcess | null = null;
let serverPort: number = 0;

export function getStatus(): ServerStatus { /* ... */ }

export async function startServer(projectPath: string): Promise<number> {
  // 1. 查找 Python 可执行文件
  const pythonPath = await findPython(projectPath);
  // 优先: .venv/Scripts/python.exe, 其次 PATH 中的 python

  // 2. 选择一个可用端口
  serverPort = await findAvailablePort(8765);

  // 3. spawn 子进程
  pythonProcess = spawn(pythonPath, [
    '-m', 'SmallShrimp.server.server',
    '--port', String(serverPort),
  ], {
    cwd: projectPath,
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  // 4. 收集 stderr 日志
  pythonProcess.stderr?.on('data', (data) => {
    logBuffer.push(data.toString());
  });

  // 5. 监听进程退出
  pythonProcess.on('exit', (code) => {
    if (autoRestart && code !== 0) {
      setTimeout(() => startServer(projectPath), 2000);
    }
  });

  // 6. 健康检查轮询
  await waitForHealth(serverPort, 30000); // 30s 超时
  return serverPort;
}

export function stopServer(): void {
  pythonProcess?.kill('SIGTERM');
  pythonProcess = null;
}
```

### 2.3 健康检查

```typescript
async function waitForHealth(port: number, timeoutMs: number): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      await httpGet(`http://localhost:${port}/health`);
      return; // 成功
    } catch {
      await sleep(500); // 每 500ms 重试
    }
  }
  throw new Error(`Server 启动超时 (${timeoutMs}ms)`);
}
```

### 2.4 端口分配

- 默认尝试 `8765`
- 被占用则递增：`8766`, `8767`...
- 端口号通过 IPC 传给 Renderer

### 2.5 Python 环境查找

```
优先级:
1. {projectPath}/.venv/Scripts/python.exe  (Windows)
2. {projectPath}/.venv/bin/python           (macOS/Linux)
3. PATH 中的 python3 / python
4. 用户手动指定路径
```

---

## 3. 托盘管理 (`tray.ts`)

### 3.1 状态图标

| 状态 | 图标 | NativeImage 生成方式 |
|------|------|---------------------|
| STOPPED | 灰色圆点 | `createTrayIcon('#9ca3af')` |
| STARTING | 黄色圆点 | `createTrayIcon('#facc15')` |
| RUNNING | 绿色圆点 | `createTrayIcon('#22c55e')` |
| ERROR | 红色圆点 | `createTrayIcon('#ef4444')` |

图标通过 Canvas 动态绘制 16x16 圆形（避免依赖外部图片文件）。

### 3.2 右键菜单

```
┌─────────────────────┐
│ 🟢 SmallShrimp      │  ← 状态指示
├─────────────────────┤
│ 显示主窗口           │  ← 单击托盘 = 此操作
│ ─────────────────── │
│ 启动服务  /  停止服务 │  ← 根据状态切换
│ ─────────────────── │
│ 开机自启 (☑/☐)      │  ← P2
│ ─────────────────── │
│ 退出                 │
└─────────────────────┘
```

### 3.3 实现

```typescript
// tray.ts
import { Tray, Menu, nativeImage } from 'electron';

let tray: Tray | null = null;

export function createTray(mainWindow: BrowserWindow) {
  tray = new Tray(createStatusIcon('stopped'));
  tray.setToolTip('SmallShrimp');

  tray.on('click', () => {
    mainWindow.show();
    mainWindow.focus();
  });

  updateTrayMenu('stopped');
}

export function updateTrayStatus(status: ServerStatus) {
  tray?.setImage(createStatusIcon(status));
  updateTrayMenu(status);
}
```

---

## 4. IPC 通道注册 (`ipc-handlers.ts`)

### 4.1 通道清单

```typescript
// 集中注册，避免散落
export function registerIpcHandlers() {
  // Python 进程控制
  ipcMain.handle('START_SERVER', async () => {
    const port = await startServer(getProjectPath());
    return { port };
  });
  ipcMain.handle('STOP_SERVER', async () => {
    stopServer();
    return { success: true };
  });
  ipcMain.handle('GET_SERVER_STATUS', () => {
    return { status: getStatus(), port: serverPort };
  });

  // 窗口控制
  ipcMain.handle('MINIMIZE_TO_TRAY', (event) => {
    BrowserWindow.fromWebContents(event.sender)?.hide();
  });

  // 文件操作（供 Agent 管理 / 配置管理使用）
  ipcMain.handle('READ_FILE', async (_, path: string) => {
    return fs.readFileSync(path, 'utf-8');
  });
  ipcMain.handle('WRITE_FILE', async (_, path: string, content: string) => {
    fs.writeFileSync(path, content, 'utf-8');
    return { success: true };
  });

  // 版本信息
  ipcMain.handle('GET_APP_VERSION', () => app.getVersion());
}
```

### 4.2 Preload 暴露

```typescript
// src/preload/index.ts
import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('electronAPI', {
  startServer: () => ipcRenderer.invoke('START_SERVER'),
  stopServer: () => ipcRenderer.invoke('STOP_SERVER'),
  getServerStatus: () => ipcRenderer.invoke('GET_SERVER_STATUS'),
  minimizeToTray: () => ipcRenderer.invoke('MINIMIZE_TO_TRAY'),
  readFile: (path: string) => ipcRenderer.invoke('READ_FILE', path),
  writeFile: (path: string, content: string) =>
    ipcRenderer.invoke('WRITE_FILE', path, content),
  getAppVersion: () => ipcRenderer.invoke('GET_APP_VERSION'),
  // 从 Main Process 推送到 Renderer 的事件
  onServerStatusChange: (cb: (status: ServerStatus) => void) => {
    ipcRenderer.on('SERVER_STATUS', (_, data) => cb(data));
  },
});
```

---

## 5. Renderer 层：主题系统

### 5.1 主题实现

使用 Tailwind `dark:` + CSS 变量，不依赖组件库主题方案。

```typescript
// stores/themeStore.ts
import { create } from 'zustand';

type Theme = 'light' | 'dark' | 'system';

export const useThemeStore = create<ThemeStore>((set) => ({
  theme: (localStorage.getItem('theme') as Theme) || 'system',
  setTheme: (theme: Theme) => {
    localStorage.setItem('theme', theme);
    applyTheme(theme);
    set({ theme });
  },
}));

function applyTheme(theme: Theme) {
  const isDark =
    theme === 'dark' ||
    (theme === 'system' &&
      window.matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.classList.toggle('dark', isDark);
}
```

### 5.2 字体设置

```typescript
// stores/fontStore.ts
export const useFontStore = create<FontStore>((set) => ({
  fontSize: Number(localStorage.getItem('fontSize')) || 14,
  fontFamily: localStorage.getItem('fontFamily') || 'system-ui',
  setFontSize: (size: number) => {
    localStorage.setItem('fontSize', String(size));
    document.documentElement.style.setProperty('--font-size', `${size}px`);
    set({ fontSize: size });
  },
}));
```

---

## 6. Renderer 层：全局快捷键 (P1)

```typescript
// main/ipc-handlers.ts
import { globalShortcut } from 'electron';

app.on('ready', () => {
  globalShortcut.register('CommandOrControl+Shift+S', () => {
    mainWindow.show();
    mainWindow.focus();
  });
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});
```

快捷键可在设置中自定义（P2）。

---

## 7. 打包配置

```yaml
# electron-builder.yml
appId: com.smallshrimp.desktop
productName: SmallShrimp
directories:
  output: dist

win:
  target:
    - target: nsis
      arch: [x64]
  icon: resources/icon.ico

nsis:
  oneClick: false
  allowToChangeInstallationDirectory: true
  createDesktopShortcut: true

mac:
  target: dmg
  icon: resources/icon.icns

linux:
  target: AppImage
  icon: resources/icon.png
```

---

## 8. 文件清单

| 文件 | 新建/修改 | 说明 |
|------|----------|------|
| `src/main/index.ts` | 新建 | 入口 |
| `src/main/python.ts` | 新建 | 进程管理 |
| `src/main/tray.ts` | 新建 | 托盘 |
| `src/main/ipc-handlers.ts` | 新建 | IPC 注册 |
| `src/main/updater.ts` | 新建 | 自动更新 (P2) |
| `src/preload/index.ts` | 新建 | contextBridge |
| `src/shared/ipc-channels.ts` | 新建 | 通道常量 |
| `src/shared/types.ts` | 新建 | 共享类型 |
| `src/renderer/stores/serverStore.ts` | 新建 | Server 状态 |
| `src/renderer/stores/themeStore.ts` | 新建 | 主题 |
| `src/renderer/components/layout/TitleBar.tsx` | 新建 | 自定义标题栏 |
| `src/renderer/components/layout/MainLayout.tsx` | 新建 | 布局容器 |
| `src/renderer/components/common/ServerStatus.tsx` | 新建 | 状态指示器 |
| `electron-builder.yml` | 新建 | 打包配置 |
| `package.json` | 新建 | 项目配置 |

---

## 9. 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-25 | v0.1 | 初始版本 |
