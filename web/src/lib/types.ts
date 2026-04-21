export interface ActionReference {
  type: "issue" | "pr" | "link" | "email";
  url: string;
  title: string;
}

export interface ActionItem {
  id: string;
  brief_id: string;
  category: string;
  title: string;
  description: string;
  priority: "critical" | "high" | "medium" | "low";
  status: "pending" | "in-progress" | "resolved" | "dismissed";
  chat_session_id: string | null;
  references: ActionReference[];
  created_at: number;
  updated_at: number;
}

export interface Brief {
  id: string;
  summary: string;
  data_sources: string;
  created_at: number;
  cover_url: string;
  suggested_prompts: string[];
  action_items: ActionItem[];
}

export interface WorkspaceStatus {
  onboarding: string;
  blueprint: {
    summary: string;
    data: Record<string, unknown>;
    updated_at: number;
  } | null;
  learnings_count: number;
  learnings: Array<{
    id: number;
    category: string;
    content: string;
    created_at: number;
  }>;
}

export interface ChatEvent {
  type: "text" | "tool_start" | "thinking" | "thinking_done" | "reasoning" | "done" | "error";
  content?: string;
  name?: string;
  preview?: string;
  args?: string;
  threadId?: string;
  response?: string;
  message?: string;
}

export interface ToolState {
  name: string;
  preview: string;
  args: string;
  status: "running" | "done";
  startedAt: number;
}

export interface Attachment {
  name: string;
  type: string;       // mime type
  size: number;
  content: string;    // text content or base64 (for images)
  isImage: boolean;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools?: string[];
  attachments?: Attachment[];
}

export interface Session {
  id: string;
  source: string;
  model: string;
  title: string | null;
  started_at: number;
  ended_at: number | null;
  message_count: number;
  preview: string;
  last_active: number;
}
