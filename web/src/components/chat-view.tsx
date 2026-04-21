"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ui/conversation";
import { Message, MessageContent } from "@/components/ui/message";
import { RichResponse } from "@/components/rich-response";
import { Badge } from "@/components/ui/badge";
import { streamChat, fetchSessionMessages, fetchBrief } from "@/lib/api";
import type { ChatMessage, ToolState, Attachment } from "@/lib/types";
import {
  Send,
  Square,
  Loader2,
  Brain,
  Wrench,
  CheckCircle2,
  Paperclip,
  X,
  Copy,
  Check,
  FileText,
  Image as ImageIcon,
} from "lucide-react";
import { DashLogo } from "@/components/dash-logo";
import { cn } from "@/lib/utils";

const DEFAULT_SUGGESTIONS = [
  "Give me today's brief",
  "What are the top risks right now?",
  "What should we build next?",
  "Draft a stakeholder update",
];

const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5 MB
const ACCEPTED_TYPES = "image/*,.txt,.md,.json,.csv,.log,.yaml,.yml,.py,.js,.ts,.tsx,.jsx,.html,.css,.sh";

interface Props {
  initialPrompt: string | null;
  resumeSessionId: string | null;
  onPromptConsumed: () => void;
  onSessionCreated: () => void;
}

type AgentState = "idle" | "thinking" | "reasoning" | "tool_running" | "responding";

export function ChatView({
  initialPrompt,
  resumeSessionId,
  onPromptConsumed,
  onSessionCreated,
}: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [abortController, setAbortController] = useState<AbortController | null>(null);
  const [threadId, setThreadId] = useState<string | null>(resumeSessionId);
  const [streamingText, setStreamingText] = useState("");
  const [agentState, setAgentState] = useState<AgentState>("idle");
  const [thinkingText, setThinkingText] = useState("");
  const [reasoningText, setReasoningText] = useState("");
  const [activeTools, setActiveTools] = useState<ToolState[]>([]);
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>(DEFAULT_SUGGESTIONS);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [attachmentError, setAttachmentError] = useState<string>("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const consumedRef = useRef(false);

  // Load contextual suggestions from latest brief
  useEffect(() => {
    fetchBrief().then((brief) => {
      if (!brief) return;
      if (brief.suggested_prompts?.length > 0) {
        setSuggestions(brief.suggested_prompts.slice(0, 4));
        return;
      }
      const pending = (brief.action_items ?? []).filter((a) => a.status === "pending");
      const dynamic: string[] = ["Give me today's brief"];
      const critical = pending.find((a) => a.priority === "critical");
      if (critical) dynamic.push(`Investigate: ${critical.title}`);
      dynamic.push("What should we build next?");
      dynamic.push("Draft a stakeholder update");
      setSuggestions(dynamic.slice(0, 4));
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (resumeSessionId) {
      setLoading(true);
      setThreadId(resumeSessionId);
      fetchSessionMessages(resumeSessionId).then((msgs) => {
        setMessages(msgs);
        setLoading(false);
      });
    }
  }, [resumeSessionId]);

  useEffect(() => {
    if (initialPrompt && !consumedRef.current) {
      consumedRef.current = true;
      onPromptConsumed();
      send(initialPrompt);
    }
  }, [initialPrompt]);

  // Auto-resize textarea
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 320) + "px";
  }, [input]);

  // ── File attachments ──────────────────────────────────────────────

  async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    if (!files.length) return;
    setAttachmentError("");

    for (const file of files) {
      if (file.size > MAX_FILE_SIZE) {
        setAttachmentError(`${file.name} is larger than 5MB`);
        continue;
      }

      try {
        const isImage = file.type.startsWith("image/");
        const content = isImage
          ? await readFileAsDataURL(file)
          : await readFileAsText(file);

        setAttachments((prev) => [
          ...prev,
          {
            name: file.name,
            type: file.type || "text/plain",
            size: file.size,
            content,
            isImage,
          },
        ]);
      } catch (err) {
        setAttachmentError(`Could not read ${file.name}`);
      }
    }

    // Reset input so same file can be picked again
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function removeAttachment(index: number) {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  }

  // ── Send ──────────────────────────────────────────────────────────

  function handleInterrupt() {
    if (abortController) {
      abortController.abort();
      setAbortController(null);
      // Commit whatever we have so far
      if (streamingText) {
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: "assistant",
            content: streamingText + "\n\n*[Interrupted]*",
          },
        ]);
        setStreamingText("");
      }
      setActiveTools([]);
      setAgentState("idle");
      setSending(false);
    }
  }

  const send = useCallback(
    async (text?: string, files?: Attachment[]) => {
      const msg = text ?? input.trim();
      const currentAttachments = files ?? attachments;
      if ((!msg && currentAttachments.length === 0) || sending) return;

      const ac = new AbortController();
      setAbortController(ac);

      setInput("");
      setAttachments([]);
      setAttachmentError("");
      setSending(true);
      setStreamingText("");
      setActiveTools([]);
      setAgentState("thinking");
      setThinkingText("");
      setReasoningText("");

      const userMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content: msg,
        attachments: currentAttachments.length > 0 ? currentAttachments : undefined,
      };
      setMessages((prev) => [...prev, userMsg]);

      let fullText = "";
      const tools: ToolState[] = [];
      const toolNames: string[] = [];

      await streamChat(
        msg,
        threadId,
        (event) => {
          if (event.type === "thinking" && event.content) {
            setAgentState("thinking");
            setThinkingText(event.content);
          }
          if (event.type === "thinking_done") setThinkingText("");
          if (event.type === "reasoning" && event.content) {
            setAgentState("reasoning");
            setReasoningText(event.content);
          }
          if (event.type === "tool_start" && event.name) {
            setAgentState("tool_running");
            const tool: ToolState = {
              name: event.name,
              preview: event.preview || "",
              args: event.args || "",
              status: "running",
              startedAt: Date.now(),
            };
            tools.push(tool);
            toolNames.push(event.name);
            setActiveTools([...tools]);
          }
          if (event.type === "text" && event.content) {
            setAgentState("responding");
            for (const t of tools) t.status = "done";
            setActiveTools([...tools]);
            fullText += event.content;
            setStreamingText(fullText);
          }
          if (event.type === "done") {
            if (event.threadId) setThreadId(event.threadId);
            const finalText = event.response ?? fullText;
            for (const t of tools) t.status = "done";
            setMessages((prev) => [
              ...prev,
              {
                id: crypto.randomUUID(),
                role: "assistant",
                content: finalText,
                tools: toolNames.length > 0 ? toolNames : undefined,
              },
            ]);
            setStreamingText("");
            setActiveTools([]);
            setAgentState("idle");
            onSessionCreated();
          }
          if (event.type === "error") {
            setMessages((prev) => [
              ...prev,
              {
                id: crypto.randomUUID(),
                role: "assistant",
                content: `Error: ${event.message}`,
              },
            ]);
            setStreamingText("");
            setActiveTools([]);
            setAgentState("idle");
          }
        },
        currentAttachments,
        ac,
      );

      setAbortController(null);
      setSending(false);
    },
    [input, attachments, sending, threadId, onSessionCreated],
  );

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  function handleSubmit(text: string) {
    setInput("");
    send(text);
  }

  const isEmpty = messages.length === 0 && !streamingText && !loading;

  return (
    <div className="flex h-full flex-col">
      <Conversation className="flex-1">
        <ConversationContent className="mx-auto max-w-3xl px-6">
          {loading ? (
            <div className="flex items-center justify-center pt-24">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              <span className="ml-2 text-sm text-muted-foreground">
                Loading conversation...
              </span>
            </div>
          ) : isEmpty ? (
            <div className="flex flex-col items-center pt-24 text-center">
              <DashLogo size={48} />
              <h2 className="mt-5 text-xl font-semibold tracking-tight">
                What can I help with?
              </h2>
              <p className="mt-2 text-sm text-muted-foreground">
                I have full context on your team, repos, and project boards.
              </p>
              <div className="mt-8 flex flex-wrap justify-center gap-2">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => handleSubmit(s)}
                    className="rounded-full border border-border bg-card px-4 py-2 text-[13px] text-muted-foreground transition-colors hover:border-primary/30 hover:text-foreground"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-2 py-6">
              {messages.map((msg) => (
                <ChatMessageBubble key={msg.id} msg={msg} />
              ))}

              {/* Streaming / active state */}
              {sending && (
                <Message from="assistant">
                  <MessageContent variant="flat">
                    <AgentStateIndicator
                      state={agentState}
                      thinkingText={thinkingText}
                      reasoningText={reasoningText}
                    />
                    {activeTools.length > 0 && <ToolBadges tools={activeTools} />}
                    {streamingText ? (
                      <RichResponse>{streamingText}</RichResponse>
                    ) : !streamingText && activeTools.length === 0 && agentState !== "responding" ? (
                      <span className="text-sm text-muted-foreground">
                        {agentState === "thinking" ? "" : "Waiting for response..."}
                      </span>
                    ) : null}
                  </MessageContent>
                </Message>
              )}
            </div>
          )}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>

      {/* Input area */}
      <div className="border-t border-border bg-background px-6 py-4">
        <div className="mx-auto max-w-3xl">
          {/* Attachment chips */}
          {attachments.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-2">
              {attachments.map((a, i) => (
                <AttachmentChip
                  key={i}
                  attachment={a}
                  onRemove={() => removeAttachment(i)}
                />
              ))}
            </div>
          )}

          {attachmentError && (
            <p className="mb-2 text-xs text-red-600">{attachmentError}</p>
          )}

          {/* Input box */}
          <div className="flex items-end gap-2 rounded-xl border border-border bg-card px-3 py-2 focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-primary/10 transition-all">
            {/* Attach button */}
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={sending}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-30"
              title="Attach file"
            >
              <Paperclip className="h-4 w-4" />
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ACCEPTED_TYPES}
              onChange={handleFileSelect}
              className="hidden"
            />

            {/* Textarea */}
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Message Dash..."
              rows={1}
              className="flex-1 resize-none bg-transparent py-1.5 text-sm leading-relaxed outline-none placeholder:text-muted-foreground"
              style={{ maxHeight: 320, minHeight: 24 }}
              disabled={sending}
            />

            {/* Send / Stop button */}
            {sending ? (
              <button
                onClick={handleInterrupt}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-destructive text-destructive-foreground transition-colors hover:bg-destructive/90"
                title="Stop generating"
              >
                <Square className="h-3.5 w-3.5" />
              </button>
            ) : (
              <button
                onClick={() => send()}
                disabled={!input.trim() && attachments.length === 0}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-opacity disabled:opacity-30"
              >
                <Send className="h-4 w-4" />
              </button>
            )}
          </div>

          <p className="mt-2 text-center text-[11px] text-muted-foreground">
            Enter to send · Shift+Enter for new line · Attach images, code, docs (max 5MB)
          </p>
        </div>
      </div>
    </div>
  );
}

// ── Subcomponents ─────────────────────────────────────────────────────

function ChatMessageBubble({ msg }: { msg: ChatMessage }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(msg.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="group">
      <Message from={msg.role}>
        <MessageContent variant={msg.role === "assistant" ? "flat" : "contained"}>
          {/* Attachments preview */}
          {msg.attachments && msg.attachments.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-2">
              {msg.attachments.map((a, i) => (
                <div key={i} className="inline-flex items-center gap-1.5 rounded-lg bg-background/60 px-2.5 py-1.5 text-xs">
                  {a.isImage ? <ImageIcon className="h-3.5 w-3.5" /> : <FileText className="h-3.5 w-3.5" />}
                  <span className="font-medium">{a.name}</span>
                </div>
              ))}
            </div>
          )}

          {msg.role === "assistant" ? (
            <div>
              {msg.tools && msg.tools.length > 0 && (
                <ToolBadges
                  tools={msg.tools.map((t) => ({
                    name: t,
                    status: "done" as const,
                    preview: "",
                    args: "",
                    startedAt: 0,
                  }))}
                />
              )}
              <RichResponse>{msg.content}</RichResponse>
            </div>
          ) : (
            <span className="whitespace-pre-wrap">{msg.content}</span>
          )}
        </MessageContent>
      </Message>

      {/* Copy button — below the message, visible on hover */}
      {msg.content && (
        <div
          className={cn(
            "flex h-6 items-center opacity-0 group-hover:opacity-100 transition-opacity -mt-1 mb-2",
            msg.role === "user" ? "justify-end pr-2" : "justify-start pl-10"
          )}
        >
          <button
            onClick={handleCopy}
            className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
            title="Copy message"
          >
            {copied ? (
              <>
                <Check className="h-3 w-3 text-green-500" />
                <span className="text-green-600">Copied</span>
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" />
                <span>Copy</span>
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
}

function AttachmentChip({ attachment, onRemove }: { attachment: Attachment; onRemove: () => void }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-lg border border-border bg-card pl-2 pr-1 py-1 text-xs">
      {attachment.isImage ? (
        <ImageIcon className="h-3.5 w-3.5 text-muted-foreground" />
      ) : (
        <FileText className="h-3.5 w-3.5 text-muted-foreground" />
      )}
      <span className="font-medium max-w-[180px] truncate">{attachment.name}</span>
      <span className="text-muted-foreground text-[10px]">
        {(attachment.size / 1024).toFixed(1)}KB
      </span>
      <button
        onClick={onRemove}
        className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}

function AgentStateIndicator({
  state,
  thinkingText,
  reasoningText,
}: {
  state: AgentState;
  thinkingText: string;
  reasoningText: string;
}) {
  if (state === "idle") return null;

  return (
    <div className="mb-3 flex items-center gap-2">
      {state === "thinking" && (
        <>
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-purple-100 dark:bg-purple-950">
            <Brain className="h-3.5 w-3.5 animate-pulse text-purple-600 dark:text-purple-400" />
          </div>
          <span className="text-xs font-medium text-muted-foreground">
            {thinkingText || "Thinking..."}
          </span>
        </>
      )}
      {state === "reasoning" && (
        <>
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-blue-100 dark:bg-blue-950">
            <Brain className="h-3.5 w-3.5 animate-pulse text-blue-600 dark:text-blue-400" />
          </div>
          <div className="min-w-0 flex-1">
            <span className="text-xs font-medium text-muted-foreground">Reasoning</span>
            {reasoningText && (
              <p className="mt-1 max-h-20 overflow-y-auto text-xs text-muted-foreground/70 italic leading-relaxed">
                {reasoningText.slice(-200)}
              </p>
            )}
          </div>
        </>
      )}
      {state === "tool_running" && (
        <>
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-amber-100 dark:bg-amber-950">
            <Wrench className="h-3.5 w-3.5 animate-spin text-amber-600 dark:text-amber-400" />
          </div>
          <span className="text-xs font-medium text-muted-foreground">
            Running tools...
          </span>
        </>
      )}
      {state === "responding" && (
        <>
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-green-100 dark:bg-green-950">
            <CheckCircle2 className="h-3.5 w-3.5 text-green-600 dark:text-green-400" />
          </div>
          <span className="text-xs font-medium text-muted-foreground">
            Responding
          </span>
        </>
      )}
    </div>
  );
}

function ToolBadges({ tools }: { tools: ToolState[] }) {
  return (
    <div className="mb-3 flex flex-wrap gap-1.5">
      {tools.map((t, i) => {
        const elapsed =
          t.status === "running" ? Math.floor((Date.now() - t.startedAt) / 1000) : 0;
        return (
          <div
            key={i}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium transition-all",
              t.status === "running"
                ? "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-400"
                : "border-border bg-muted text-muted-foreground"
            )}
          >
            <span
              className={cn(
                "inline-block h-1.5 w-1.5 rounded-full",
                t.status === "running"
                  ? "animate-pulse bg-amber-500"
                  : "bg-green-500"
              )}
            />
            <span>{t.name}</span>
            {t.args && (
              <span className="max-w-[150px] truncate text-[10px] opacity-60">
                {t.args}
              </span>
            )}
            {t.status === "running" && elapsed > 0 && (
              <span className="text-[10px] tabular-nums opacity-50">
                {elapsed}s
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── File reading helpers ──────────────────────────────────────────────

function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

function readFileAsDataURL(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}
