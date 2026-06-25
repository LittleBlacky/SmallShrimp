# Agent 聊天 — 技术架构设计

> 版本: v0.1 | 日期: 2026-06-25 | 状态: 草案
> 关联: @ref: PRD.md, @ref: ../../TECH-DESIGN.md

---

## 1. 组件设计

### 1.1 组件树

```
ChatPage
├── SessionList                          # 左侧会话列表
│   ├── SearchInput                      #   搜索会话
│   ├── NewSessionButton                 #   新建会话
│   └── SessionItem[]                    #   会话项（标题、时间、Agent）
│       └── ContextMenu                  #     右键菜单（重命名/删除）
│
└── ChatView                             # 右侧聊天区
    ├── MessageList (虚拟滚动)            #
    │   └── MessageItem[]                #
    │       ├── [role=user]              #   用户消息：右对齐气泡
    │       │   └── MarkdownRenderer     #
    │       └── [role=assistant]         #   AI 回复：左对齐
    │           ├── StreamingText         #     流式文本（P0）
    │           ├── MarkdownRenderer      #     渲染后的文本（完成后）
    │           └── ToolCallCard[]        #     工具调用卡片（P1）
    │
    └── InputBox                         # 底部输入区
        ├── AttachmentPreview[]          #   附件预览（P1）
        ├── TextArea                     #   文本输入
        ├── AgentSwitcher                #   Agent 下拉
        └── SendButton                   #   发送按钮
```

### 1.2 MessageItem 状态机

```
                    ┌─────────┐
   user_message ──▶ │  USER   │ (静态，Markdown 渲染)
                    └─────────┘

                    ┌──────────┐  text_delta   ┌───────────┐
   text_delta ────▶ │STREAMING │ ────────────▶ │STREAMING  │ ...追加文本
                    └──────────┘               └───────────┘
                         │ text_done
                         ▼
                    ┌─────────┐
                    │  DONE   │ (静态，Markdown 渲染)
                    └─────────┘

                    ┌──────────┐  tool_result  ┌──────────┐
   tool_call ─────▶ │TOOL_CALL │ ───────────▶ │TOOL_DONE │
                    │(展开中)   │               │(结果)    │
                    └──────────┘               └──────────┘
```

---

## 2. WebSocket 客户端

### 2.1 连接管理 (`services/ws.ts`)

```typescript
class ChatWebSocket {
  private ws: WebSocket | null = null;
  private reconnectTimer: number | null = null;
  private reconnectDelay = 1000; // 初始 1s，指数退避，上限 30s

  connect(port: number, agent: string, sessionId?: string) {
    const params = new URLSearchParams({ agent });
    if (sessionId) params.set('session_id', sessionId);

    this.ws = new WebSocket(`ws://localhost:${port}/ws/chat?${params}`);

    this.ws.onopen = () => {
      this.reconnectDelay = 1000; // 重置退避
      serverStore.setStatus('running');
    };

    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      this.dispatch(msg);
    };

    this.ws.onclose = () => {
      if (!this.intentionalClose) {
        this.scheduleReconnect();
      }
    };
  }

  send(content: string) {
    this.ws?.send(JSON.stringify({ type: 'user_message', content }));
  }

  private dispatch(msg: ServerEvent) {
    switch (msg.type) {
      case 'session_created': chatStore.setSessionId(msg.session_id); break;
      case 'text_delta':       chatStore.appendStreamingText(msg.content); break;
      case 'text_done':        chatStore.finishStreaming(); break;
      case 'tool_call':        chatStore.addToolCall(msg); break;
      case 'tool_result':      chatStore.updateToolResult(msg); break;
      case 'error':            chatStore.addError(msg); break;
    }
  }
}
```

### 2.2 React Hook 封装

```typescript
// hooks/useWebSocket.ts
export function useChatWebSocket() {
  const port = useServerStore(s => s.port);
  const agent = useAgentStore(s => s.current);
  const sessionId = useSessionStore(s => s.currentId);
  const wsRef = useRef<ChatWebSocket | null>(null);

  useEffect(() => {
    if (port && agent) {
      wsRef.current = new ChatWebSocket();
      wsRef.current.connect(port, agent, sessionId);
      return () => wsRef.current?.disconnect();
    }
  }, [port, agent]);

  // 切换会话时重连
  useEffect(() => {
    if (sessionId && wsRef.current) {
      wsRef.current.reconnect(port, agent, sessionId);
    }
  }, [sessionId]);

  return { send: (msg: string) => wsRef.current?.send(msg) };
}
```

---

## 3. Zustand Store 设计

### 3.1 chatStore

```typescript
// stores/chatStore.ts
interface ChatStore {
  messages: Message[];           // 当前会话全部消息
  streamingMessageId: string | null;  // 正在流式输出的消息 ID

  // 用户操作
  addUserMessage(content: string): void;

  // 流式输出（由 WebSocket dispatch 调用）
  startStreaming(): string;           // 创建空消息，返回 ID
  appendStreamingText(delta: string): void;
  finishStreaming(): void;

  // 工具调用（P1）
  addToolCall(toolCall: ToolCallEvent): void;
  updateToolResult(result: ToolResultEvent): void;

  // 消息操作
  clearMessages(): void;              // 切换会话时调用
  deleteMessage(id: string): void;
  retryLastMessage(): void;           // P1: 重新生成
}
```

**核心逻辑：流式追加**

```typescript
appendStreamingText: (delta) => {
  set((state) => {
    const msgs = [...state.messages];
    const last = msgs[msgs.length - 1];
    if (last?.role === 'assistant' && last.status === 'streaming') {
      msgs[msgs.length - 1] = { ...last, content: last.content + delta };
    } else {
      // 第一条 delta 到达时创建消息
      const id = generateId();
      msgs.push({ id, role: 'assistant', content: delta, status: 'streaming' });
      return { messages: msgs, streamingMessageId: id };
    }
    return { messages: msgs };
  });
},
```

### 3.2 sessionStore

```typescript
// stores/sessionStore.ts
interface SessionStore {
  sessions: SessionMeta[];       // 会话列表
  currentId: string | null;      // 当前会话
  isLoading: boolean;

  fetchSessions(): Promise<void>;      // GET /api/sessions
  createSession(): Promise<string>;     // POST /api/sessions
  switchSession(id: string): void;
  renameSession(id: string, title: string): Promise<void>;  // P1
  deleteSession(id: string): Promise<void>;
}
```

**会话切换流程：**

```
用户点击 SessionItem
  │
  ▼
sessionStore.switchSession(id)
  ├── chatStore.clearMessages()          # 清空当前消息
  ├── http.get(`/api/sessions/${id}`)    # 加载历史
  ├── chatStore.loadHistory(messages)    # 回填消息
  └── ws.reconnect(agent, id)           # WebSocket 切换会话
```

---

## 4. 虚拟滚动 (`MessageList`)

### 4.1 策略

使用 `@tanstack/react-virtual`，关键配置：

```typescript
const virtualizer = useVirtualizer({
  count: messages.length,
  getScrollElement: () => scrollRef.current,
  estimateSize: () => 120,           // 单条消息估算高度
  overscan: 5,                       // 上下各预渲染 5 条
});

// 新消息到达时自动滚到底部
useEffect(() => {
  if (isAtBottom) {
    virtualizer.scrollToIndex(messages.length - 1);
  }
}, [messages.length]);
```

### 4.2 自动滚底逻辑

```
用户状态:
  ├── 在底部附近 (≤150px) → 新消息自动滚到底部
  └── 在历史中浏览 → 不自动滚动，显示「↓ 回到底部」按钮
```

---

## 5. 流式渲染 (`StreamingText`)

### 5.1 渲染策略

不使用防抖。每个 `text_delta` 直接触发 Zustand 更新，React 自动重渲染。

```typescript
// components/chat/StreamingText.tsx
function StreamingText({ content }: { content: string }) {
  return (
    <div className="whitespace-pre-wrap">
      {content}
      <span className="animate-pulse">▌</span>  {/* 闪烁光标 */}
    </div>
  );
}
```

**性能保障：**

- `MessageItem` 用 `React.memo` + 浅比较，只重渲染变动的消息
- 流式结束时切换为静态 `MarkdownRenderer`，停止光标动画

### 5.2 从流式切换到静态

```typescript
// 在 MessageItem 中
if (msg.role === 'assistant') {
  if (msg.status === 'streaming') {
    return <StreamingText content={msg.content} />;
  }
  return <MarkdownRenderer content={msg.content} />;
}
```

---

## 6. Markdown 渲染 (`MarkdownRenderer`)

```typescript
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';

function MarkdownRenderer({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      components={{
        code({ node, className, children, ...props }) {
          const isBlock = /language-/.test(className || '');
          if (isBlock) {
            const lang = className?.replace('language-', '') || '';
            return (
              <CodeBlock language={lang} code={String(children)} />
            );
          }
          return <code className="bg-muted px-1 rounded" {...props}>{children}</code>;
        },
        // 链接在新窗口打开
        a({ href, children }) {
          return <a href={href} target="_blank" rel="noopener">{children}</a>;
        },
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
```

### 6.1 CodeBlock 组件

```typescript
function CodeBlock({ language, code }: { language: string; code: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <div className="relative rounded-md bg-muted">
      <div className="flex justify-between px-4 py-2 text-xs text-muted-foreground">
        <span>{language}</span>
        <button onClick={() => { navigator.clipboard.writeText(code); setCopied(true); }}>
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <pre className="p-4 overflow-x-auto"><code>{code}</code></pre>
    </div>
  );
}
```

---

## 7. 输入框 (`InputBox`)

### 7.1 键盘行为

```typescript
function InputBox({ onSend }: Props) {
  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
    // Shift+Enter → 换行（默认行为，不拦截）
  };

  // 草稿自动保存
  useEffect(() => {
    const timer = setInterval(() => {
      localStorage.setItem(`draft:${sessionId}`, text);
    }, 2000);
    return () => clearInterval(timer);
  }, [text, sessionId]);
}
```

### 7.2 斜杠命令（P1）

```
输入 / 弹出命令面板:
  /skill <name>   → 加载技能
  /agent <name>   → 切换 Agent
  /clear          → 清空当前会话
```

用 `<CommandPalette>` 弹层实现，`@/` 触发后显示匹配列表。

### 7.3 文件拖拽（P1）

```typescript
<div
  onDrop={(e) => {
    const files = Array.from(e.dataTransfer.files);
    files.forEach(f => addAttachment(f.path));
  }}
  onDragOver={(e) => e.preventDefault()}
>
  <TextArea ... />
  {attachments.map(a => <AttachmentPreview key={a.path} file={a} />)}
</div>
```

---

## 8. 工具调用卡片 (P1)

```typescript
// components/chat/ToolCallCard.tsx
function ToolCallCard({ toolCall }: Props) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="border rounded-md my-2">
      <button onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 px-3 py-2 w-full text-sm bg-muted/50">
        <Icon name={toolCall.tool === 'read_file' ? '📁' : '🔧'} />
        <span className="font-mono">{toolCall.tool}</span>
        <span className="ml-auto">{expanded ? '▼' : '▶'}</span>
      </button>

      {expanded && (
        <div className="p-3 text-sm">
          {toolCall.status === 'running' && <Spinner />}
          {toolCall.status === 'done' && (
            <pre className="text-xs">{toolCall.result}</pre>
          )}
          {toolCall.status === 'error' && (
            <div className="text-red-500">{toolCall.error}</div>
          )}
        </div>
      )}
    </div>
  );
}
```

---

## 9. API 调用层

```typescript
// services/api.ts
const BASE = (port: number) => `http://localhost:${port}/api`;

export async function fetchSessions(port: number): Promise<SessionMeta[]> {
  const res = await fetch(`${BASE(port)}/sessions`);
  if (!res.ok) throw new ApiError(res.status, await res.text());
  const data = await res.json();
  return data.sessions;
}

export async function fetchMessages(port: number, sessionId: string, offset = 0) {
  const res = await fetch(`${BASE(port)}/sessions/${sessionId}?offset=${offset}&limit=50`);
  return res.json();
}

export async function createSession(port: number, agent: string): Promise<string> {
  const res = await fetch(`${BASE(port)}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent }),
  });
  const data = await res.json();
  return data.session_id;
}

export async function deleteSession(port: number, id: string): Promise<void> {
  await fetch(`${BASE(port)}/sessions/${id}`, { method: 'DELETE' });
}
```

---

## 10. 文件清单（`desktop-app/` 下新建）

| 文件 | 说明 |
|------|------|
| `src/renderer/pages/ChatPage.tsx` | 聊天页面容器 |
| `src/renderer/components/chat/ChatView.tsx` | 聊天视图（消息列表 + 输入框） |
| `src/renderer/components/chat/MessageList.tsx` | 虚拟滚动消息列表 |
| `src/renderer/components/chat/MessageItem.tsx` | 单条消息（状态机驱动渲染） |
| `src/renderer/components/chat/InputBox.tsx` | 输入框（快捷键、草稿保存） |
| `src/renderer/components/chat/StreamingText.tsx` | 流式文本 + 闪烁光标 |
| `src/renderer/components/chat/MarkdownRenderer.tsx` | Markdown + 代码高亮 |
| `src/renderer/components/chat/CodeBlock.tsx` | 代码块（语法标签 + 复制） |
| `src/renderer/components/chat/ToolCallCard.tsx` | 工具调用卡片 (P1) |
| `src/renderer/components/session/SessionList.tsx` | 会话列表 |
| `src/renderer/components/session/SessionItem.tsx` | 会话项 + 右键菜单 |
| `src/renderer/stores/chatStore.ts` | 聊天状态 |
| `src/renderer/stores/sessionStore.ts` | 会话状态 |
| `src/renderer/hooks/useWebSocket.ts` | WebSocket 连接 Hook |
| `src/renderer/hooks/useStreaming.ts` | 流式处理 Hook |
| `src/renderer/services/ws.ts` | WebSocket 客户端类 |
| `src/renderer/services/api.ts` | HTTP API 封装 |

---

## 11. 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-25 | v0.1 | 初始版本 |
