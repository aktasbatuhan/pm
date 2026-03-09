import { useCallback, useRef, useState, useEffect } from "react";
import { X, Send, Square, Wrench, Brain } from "lucide-react";
import { cn } from "@/lib/utils";
import { useChat } from "@/hooks/use-chat";

interface ChatDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function ChatDrawer({ open, onClose }: ChatDrawerProps) {
  const [width, setWidth] = useState(() => {
    const saved = localStorage.getItem("chat-drawer-width");
    return saved ? parseInt(saved) : 480;
  });
  const [input, setInput] = useState("");
  const dragging = useRef(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const chat = useChat();

  const onMouseDown = useCallback(() => {
    dragging.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const newWidth = Math.min(Math.max(window.innerWidth - e.clientX, 360), window.innerWidth * 0.8);
      setWidth(newWidth);
    };
    const onMouseUp = () => {
      if (dragging.current) {
        dragging.current = false;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        localStorage.setItem("chat-drawer-width", String(width));
      }
    };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [width]);

  // Auto-scroll on new content
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat.messages, chat.streamContent]);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || chat.streaming) return;
    setInput("");
    chat.sendMessage(text);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [input, chat]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  // Auto-resize textarea
  const handleInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, []);

  return (
    <div
      className={cn(
        "fixed top-0 right-0 h-full border-l border-border bg-card flex flex-col transition-transform duration-200 z-50",
        open ? "translate-x-0" : "translate-x-full"
      )}
      style={{ width }}
    >
      {/* Resize handle */}
      <div
        className="absolute left-0 top-0 bottom-0 w-1.5 cursor-col-resize hover:bg-primary/20 transition-colors"
        onMouseDown={onMouseDown}
      />

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <div>
          <h3 className="text-sm font-medium text-foreground">
            {chat.activeSessionId ? "Chat" : "New Chat"}
          </h3>
          <div className="flex gap-3 mt-0.5">
            <span className="label-uppercase">MSGS: {chat.messageCount}</span>
            <span className="label-uppercase">COST: ${chat.cost.toFixed(2)}</span>
          </div>
        </div>
        <button
          onClick={onClose}
          className="text-muted-foreground hover:text-foreground transition-colors p-1"
        >
          <X size={16} />
        </button>
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {chat.messages.length === 0 && !chat.streaming ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <p className="text-muted-foreground text-sm">Start a conversation</p>
            <p className="text-muted-foreground/50 text-xs mt-1">
              Ask about your project, sprint, or team
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {chat.messages.map((msg) => (
              <div
                key={msg.id}
                className={cn(
                  "text-xs leading-relaxed",
                  msg.role === "user"
                    ? "bg-muted/50 rounded-md px-3 py-2 ml-8"
                    : "text-foreground"
                )}
              >
                {msg.role === "user" && (
                  <span className="label-uppercase block mb-1">YOU</span>
                )}
                <div className="whitespace-pre-wrap">{msg.content}</div>
              </div>
            ))}

            {/* Streaming indicators */}
            {chat.thinking && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Brain size={12} className="animate-pulse text-primary" />
                <span>Thinking...</span>
              </div>
            )}

            {chat.tools.length > 0 && (
              <div className="flex flex-col gap-1">
                {chat.tools.map((tool, i) => (
                  <div key={i} className="flex items-center gap-2 text-[10px] text-muted-foreground">
                    <Wrench size={10} className="text-primary/60" />
                    <span>{tool.label || tool.tool}</span>
                    {tool.detail && <span className="text-muted-foreground/50">— {tool.detail}</span>}
                  </div>
                ))}
              </div>
            )}

            {chat.streamContent && (
              <div className="text-xs leading-relaxed text-foreground whitespace-pre-wrap">
                {chat.streamContent}
                <span className="inline-block w-1.5 h-3 bg-primary/60 animate-pulse ml-0.5" />
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="border-t border-border p-3 shrink-0">
        <div className="flex items-end gap-2">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder="Message..."
            rows={1}
            className="flex-1 bg-background border border-border rounded-md px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground resize-none focus:outline-none focus:ring-1 focus:ring-primary/50"
            style={{ maxHeight: 160 }}
          />
          {chat.streaming ? (
            <button
              onClick={chat.stopStream}
              className="p-2 rounded-md bg-destructive/20 text-destructive hover:bg-destructive/30 transition-colors shrink-0"
            >
              <Square size={16} />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className={cn(
                "p-2 rounded-md transition-colors shrink-0",
                input.trim()
                  ? "bg-primary text-primary-foreground hover:bg-primary/90"
                  : "bg-muted text-muted-foreground"
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
