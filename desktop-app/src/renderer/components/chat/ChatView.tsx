import {useChatStore} from "../../stores/chatStore";
import type {Message, ToolCall} from "@shared/types";
import {useState} from "react";

export function ChatView({onSend}: {onSend: (msg: string) => void}) {
  const messages = useChatStore((s: {messages: Message[]}) => s.messages);
  const [input, setInput] = useState("");

  const handleSend = () => {
    const text = input.trim();
    if (!text) return;
    useChatStore.getState().addUserMessage(text);
    onSend(text);
    setInput("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-muted-foreground mt-20">
            <p className="text-lg">🦐 开始与 Agent 对话</p>
            <p className="text-sm mt-2">输入消息开始聊天</p>
          </div>
        )}
        {messages.map((msg: Message) => (
          <MessageItem key={msg.id} message={msg} />
        ))}
      </div>

      {/* 输入框 */}
      <div className="border-t p-4">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入消息... (Shift+Enter 换行)"
            rows={2}
            className="flex-1 resize-none rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim()}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 self-end"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  );
}

function MessageItem({message}: {message: Message}) {
  const isUser = message.role === "user";
  const isStreaming = message.status === "streaming";
  const isError = message.status === "error";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-lg px-4 py-2 ${
          isUser
            ? "bg-blue-600 text-white"
            : isError
              ? "bg-red-50 border border-red-200 text-red-700"
              : "bg-gray-100 dark:bg-gray-800"
        }`}
      >
        <div className="whitespace-pre-wrap text-sm">
          {message.content}
          {isStreaming && <span className="animate-pulse ml-0.5">▌</span>}
        </div>
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mt-2 space-y-1">
            {message.toolCalls.map((tc: ToolCall) => (
              <ToolCallBadge key={tc.id} tool={tc.tool} status={tc.status} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ToolCallBadge({tool, status}: {tool: string; status: string}) {
  const icons: Record<string, string> = {
    read_file: "📁",
    write_file: "✏️",
    shell: "💻",
    web_search: "🔍",
    web_read: "🌐",
  };

  return (
    <div className="flex items-center gap-1 text-xs bg-white/50 dark:bg-black/20 rounded px-2 py-1">
      <span>{icons[tool] || "🔧"}</span>
      <span className="font-mono">{tool}</span>
      {status === "running" && <span className="animate-spin">⏳</span>}
      {status === "done" && <span className="text-green-600">✓</span>}
    </div>
  );
}
