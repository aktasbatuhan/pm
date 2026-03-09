import { useCallback, useRef, useState } from "react";
import { streamSSE } from "@/lib/sse";
import { apiGet, apiPost } from "@/lib/api";
import type { ChatMessage, ChatSession } from "@/types/api";

interface ToolEvent {
  tool: string;
  label?: string;
  detail?: string;
}

interface ChatState {
  sessions: ChatSession[];
  activeSessionId: string | null;
  messages: ChatMessage[];
  streaming: boolean;
  streamContent: string;
  thinking: boolean;
  thinkingContent: string;
  tools: ToolEvent[];
  cost: number;
  messageCount: number;
}

export function useChat() {
  const [state, setState] = useState<ChatState>({
    sessions: [],
    activeSessionId: null,
    messages: [],
    streaming: false,
    streamContent: "",
    thinking: false,
    thinkingContent: "",
    tools: [],
    cost: 0,
    messageCount: 0,
  });
  const abortRef = useRef<AbortController | null>(null);

  const loadSessions = useCallback(async () => {
    const data = await apiGet<ChatSession[]>("/sessions");
    setState((s) => ({ ...s, sessions: data }));
  }, []);

  const loadMessages = useCallback(async (sessionId: string) => {
    const data = await apiGet<ChatMessage[]>(`/sessions/${sessionId}/messages`);
    setState((s) => ({
      ...s,
      activeSessionId: sessionId,
      messages: data,
      messageCount: data.filter((m) => m.role !== "system").length,
    }));
  }, []);

  const createSession = useCallback(async () => {
    const data = await apiPost<{ id: string; name: string }>("/sessions", {
      name: "New Chat",
    });
    setState((s) => ({
      ...s,
      activeSessionId: data.id,
      sessions: [{ ...data, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() }, ...s.sessions],
      messages: [],
      messageCount: 0,
      cost: 0,
    }));
    return data.id;
  }, []);

  const sendMessage = useCallback(
    async (content: string) => {
      let sessionId = state.activeSessionId;
      if (!sessionId) {
        sessionId = await createSession();
      }

      const userMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content,
        createdAt: new Date().toISOString(),
      };

      setState((s) => ({
        ...s,
        messages: [...s.messages, userMsg],
        streaming: true,
        streamContent: "",
        thinking: false,
        thinkingContent: "",
        tools: [],
        messageCount: s.messageCount + 1,
      }));

      try {
        for await (const event of streamSSE("/api/chat", {
          message: content,
          sessionId,
        })) {
          const data = event.data ? JSON.parse(event.data) : {};

          switch (event.event) {
            case "thinking":
              setState((s) => ({ ...s, thinking: true, thinkingContent: "" }));
              break;
            case "thinking_delta":
              setState((s) => ({
                ...s,
                thinkingContent: s.thinkingContent + (data.content || ""),
              }));
              break;
            case "typing":
              setState((s) => ({ ...s, thinking: false }));
              break;
            case "delta":
              setState((s) => ({
                ...s,
                streamContent: s.streamContent + (data.content || ""),
              }));
              break;
            case "tool":
              setState((s) => ({
                ...s,
                tools: [...s.tools, data as ToolEvent],
              }));
              break;
            case "done": {
              const assistantMsg: ChatMessage = {
                id: crypto.randomUUID(),
                role: "assistant",
                content: "",
                createdAt: new Date().toISOString(),
              };
              setState((s) => {
                assistantMsg.content = s.streamContent;
                return {
                  ...s,
                  messages: [...s.messages, assistantMsg],
                  streaming: false,
                  streamContent: "",
                  thinking: false,
                  thinkingContent: "",
                  tools: [],
                  cost: s.cost + (data.costUsd || 0),
                  messageCount: s.messageCount + 1,
                };
              });
              break;
            }
            case "error":
              setState((s) => ({
                ...s,
                streaming: false,
                streamContent: "",
              }));
              break;
          }
        }
      } catch (err) {
        console.error("[chat] Stream error:", err);
        setState((s) => ({ ...s, streaming: false, streamContent: "" }));
      }
    },
    [state.activeSessionId, createSession]
  );

  const stopStream = useCallback(() => {
    abortRef.current?.abort();
    setState((s) => ({ ...s, streaming: false }));
  }, []);

  return {
    ...state,
    loadSessions,
    loadMessages,
    createSession,
    sendMessage,
    stopStream,
  };
}
