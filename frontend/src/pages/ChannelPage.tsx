import { useState, useEffect, useRef, useCallback } from "react";
import { Send, Square, Brain, Wrench } from "lucide-react";
import { cn } from "@/lib/utils";
import { apiGet } from "@/lib/api";
import { streamSSE } from "@/lib/sse";
import { MarkdownContent } from "@/components/ui/markdown-content";
import type { ChatMessage } from "@/types/api";

const PM_SESSION_ID = "pm-channel";

function timeLabel(dateStr: string): string {
  const d = new Date(dateStr);
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  return isToday
    ? d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function ChannelPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamContent, setStreamContent] = useState("");
  const [thinking, setThinking] = useState(false);
  const [tools, setTools] = useState<{ tool: string; label?: string }[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Load messages on mount
  useEffect(() => {
    apiGet<ChatMessage[]>(`/sessions/${PM_SESSION_ID}/messages`)
      .then((msgs) => setMessages(msgs.filter((m) => m.role !== "system")))
      .catch(() => {});
  }, []);

  // Poll for new messages when not streaming (agent might post proactively)
  useEffect(() => {
    if (streaming) return;
    const interval = setInterval(() => {
      apiGet<ChatMessage[]>(`/sessions/${PM_SESSION_ID}/messages`)
        .then((msgs) => setMessages(msgs.filter((m) => m.role !== "system")))
        .catch(() => {});
    }, 15_000);
    return () => clearInterval(interval);
  }, [streaming]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamContent]);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      createdAt: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setStreaming(true);
    setStreamContent("");
    setThinking(false);
    setTools([]);

    const abort = new AbortController();
    abortRef.current = abort;

    try {
      for await (const event of streamSSE("/api/chat", { message: text, sessionId: PM_SESSION_ID })) {
        if (abort.signal.aborted) break;
        const data = event.data ? JSON.parse(event.data) : {};
        switch (event.event) {
          case "thinking":
            setThinking(true);
            break;
          case "typing":
            setThinking(false);
            break;
          case "delta":
            setStreamContent((s) => s + (data.content || ""));
            break;
          case "tool":
            setTools((t) => [...t, data]);
            break;
          case "done": {
            const assistantMsg: ChatMessage = {
              id: crypto.randomUUID(),
              role: "assistant",
              content: "",
              createdAt: new Date().toISOString(),
            };
            setStreamContent((sc) => {
              assistantMsg.content = sc;
              return sc;
            });
            setMessages((prev) => {
              assistantMsg.content = streamContent || data.content || "";
              return [...prev, assistantMsg];
            });
            setStreaming(false);
            setStreamContent("");
            setThinking(false);
            setTools([]);
            break;
          }
          case "error":
            setStreaming(false);
            setStreamContent("");
            break;
        }
      }
    } catch {
      setStreaming(false);
      setStreamContent("");
    }
  }, [input, streaming, streamContent]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    },
    [sendMessage]
  );

  const handleInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, []);

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <div className="shrink-0 px-6 py-4 border-b border-border">
        <div className="flex items-center gap-3">
          <span className="text-xl">🧠</span>
          <div>
            <h1 className="text-sm font-medium text-foreground">Head of Product</h1>
            <p className="text-[10px] text-muted-foreground">Your direct PM channel — ideas, observations, synthesis updates</p>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {messages.length === 0 && !streaming ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <span className="text-4xl mb-4">🧠</span>
            <p className="text-sm text-muted-foreground">Your AI PM will post insights and ideas here</p>
            <p className="text-[10px] text-muted-foreground mt-1">You can also start a conversation anytime</p>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto flex flex-col gap-4">
            {messages.map((msg) => (
              <div key={msg.id} className={cn("flex gap-3", msg.role === "user" && "flex-row-reverse")}>
                {/* Avatar */}
                <div className={cn(
                  "w-7 h-7 rounded shrink-0 flex items-center justify-center text-sm",
                  msg.role === "assistant" ? "bg-primary/10" : "bg-muted"
                )}>
                  {msg.role === "assistant" ? "🧠" : "👤"}
                </div>

                {/* Bubble */}
                <div className={cn(
                  "max-w-[80%] rounded-md px-3 py-2.5",
                  msg.role === "assistant"
                    ? "bg-card border border-border"
                    : "bg-muted/60"
                )}>
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-[9px] font-medium text-foreground">
                      {msg.role === "assistant" ? "Head of Product" : "You"}
                    </span>
                    <span className="text-[8px] text-muted-foreground/50">{timeLabel(msg.createdAt)}</span>
                  </div>
                  {msg.role === "assistant" ? (
                    <MarkdownContent content={msg.content} />
                  ) : (
                    <p className="text-xs text-foreground/85 leading-relaxed">{msg.content}</p>
                  )}
                </div>
              </div>
            ))}

            {/* Streaming state */}
            {thinking && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground ml-10">
                <Brain size={12} className="animate-pulse text-primary" />
                <span>Thinking...</span>
              </div>
            )}
            {tools.length > 0 && (
              <div className="flex flex-col gap-1 ml-10">
                {tools.map((tool, i) => (
                  <div key={i} className="flex items-center gap-2 text-[10px] text-muted-foreground">
                    <Wrench size={10} className="text-primary/60" />
                    <span>{tool.label || tool.tool}</span>
                  </div>
                ))}
              </div>
            )}
            {streamContent && (
              <div className="flex gap-3">
                <div className="w-7 h-7 rounded shrink-0 flex items-center justify-center text-sm bg-primary/10">🧠</div>
                <div className="max-w-[80%] bg-card border border-border rounded-md px-3 py-2.5">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-[9px] font-medium text-foreground">Head of Product</span>
                  </div>
                  <p className="text-xs text-foreground/85 leading-relaxed whitespace-pre-wrap">
                    {streamContent}
                    <span className="inline-block w-1.5 h-3 bg-primary/60 animate-pulse ml-0.5" />
                  </p>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input */}
      <div className="shrink-0 border-t border-border px-6 py-3">
        <div className="max-w-3xl mx-auto flex items-end gap-2">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder="Message your PM agent..."
            rows={1}
            className="flex-1 bg-background border border-border rounded-md px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground resize-none focus:outline-none focus:ring-1 focus:ring-primary/50"
            style={{ maxHeight: 160 }}
          />
          {streaming ? (
            <button
              onClick={() => { abortRef.current?.abort(); setStreaming(false); }}
              className="p-2 rounded-md bg-destructive/20 text-destructive hover:bg-destructive/30 transition-colors shrink-0"
            >
              <Square size={16} />
            </button>
          ) : (
            <button
              onClick={sendMessage}
              disabled={!input.trim()}
              className={cn(
                "p-2 rounded-md transition-colors shrink-0",
                input.trim() ? "bg-primary text-primary-foreground hover:bg-primary/90" : "bg-muted text-muted-foreground"
              )}
            >
              <Send size={16} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
