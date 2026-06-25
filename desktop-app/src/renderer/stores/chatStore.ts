import {create} from "zustand";
import type {Message, ToolCall, WsEvent} from "@shared/types";

let messageId = 0;
function nextId() {
  return `msg_${++messageId}`;
}

interface ChatState {
  messages: Message[];
  currentSessionId: string | null;
  streamingMessageId: string | null;

  handleWsEvent: (event: WsEvent) => void;
  addUserMessage: (content: string) => void;
  setSessionId: (id: string) => void;
  clearMessages: () => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  currentSessionId: null,
  streamingMessageId: null,

  setSessionId: (id) => {
    set({currentSessionId: id});
  },

  addUserMessage: (content) => {
    const msg: Message = {
      id: nextId(),
      role: "user",
      content,
      status: "user",
    };
    set((s) => ({messages: [...s.messages, msg]}));
  },

  handleWsEvent: (event) => {
    switch (event.type) {
      case "session_created": {
        const sessionId = event.session_id as string;
        set({currentSessionId: sessionId});
        break;
      }

      case "text_delta": {
        const delta = event.content as string;
        set((s) => {
          const msgs = [...s.messages];
          const last = msgs[msgs.length - 1];
          if (last?.role === "assistant" && last.status === "streaming") {
            msgs[msgs.length - 1] = {...last, content: last.content + delta};
            return {messages: msgs};
          } else {
            const id = nextId();
            msgs.push({
              id,
              role: "assistant",
              content: delta,
              status: "streaming",
            });
            return {messages: msgs, streamingMessageId: id};
          }
        });
        break;
      }

      case "text_done": {
        const content = event.content as string;
        const err = event.error as string | undefined;
        set((s) => {
          const msgs = [...s.messages];
          const last = msgs[msgs.length - 1];
          if (last?.role === "assistant") {
            msgs[msgs.length - 1] = {
              ...last,
              content: err ? last.content : content,
              status: err ? "error" : "done",
            };
          } else {
            msgs.push({
              id: nextId(),
              role: "assistant",
              content: err || content,
              status: err ? "error" : "done",
            });
          }
          return {messages: msgs, streamingMessageId: null};
        });
        break;
      }

      case "tool_call": {
        const toolCall: ToolCall = {
          id: nextId(),
          tool: event.tool as string,
          args: event.args as Record<string, unknown>,
          status: "running",
        };
        set((s) => {
          const msgs = [...s.messages];
          const last = msgs[msgs.length - 1];
          if (last?.role === "assistant" && last.toolCalls) {
            last.toolCalls.push(toolCall);
            return {messages: msgs};
          }
          return s;
        });
        break;
      }

      case "tool_result": {
        const toolName = event.tool as string;
        const result = event.result as string;
        set((s) => {
          const msgs = [...s.messages];
          const last = msgs[msgs.length - 1];
          if (last?.role === "assistant" && last.toolCalls) {
            const tc = last.toolCalls.find((t) => t.tool === toolName);
            if (tc) {
              tc.status = "done";
              tc.result = result;
            }
            return {messages: msgs};
          }
          return s;
        });
        break;
      }

      case "error": {
        const msg = event.message as string;
        set((s) => ({
          messages: [
            ...s.messages,
            {id: nextId(), role: "assistant", content: msg, status: "error"},
          ],
          streamingMessageId: null,
        }));
        break;
      }
    }
  },

  clearMessages: () => {
    set({messages: [], currentSessionId: null, streamingMessageId: null});
  },
}));
