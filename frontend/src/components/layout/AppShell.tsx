import { useState, useEffect, useRef } from "react";
import { Outlet } from "react-router-dom";
import { IconNav } from "./IconNav";
import { ChatDrawer } from "./ChatDrawer";

// Custom event for opening chat with a specific session
export function openChatSession(sessionId: string, initialMessage?: string) {
  window.dispatchEvent(new CustomEvent("open-chat-session", { detail: { sessionId, initialMessage } }));
}

export function AppShell() {
  const [chatOpen, setChatOpen] = useState(false);
  const chatRef = useRef<{ loadSession: (id: string, msg?: string) => void }>(null);

  useEffect(() => {
    const handler = (e: Event) => {
      const { sessionId, initialMessage } = (e as CustomEvent).detail;
      setChatOpen(true);
      // Small delay to ensure drawer is mounted
      setTimeout(() => chatRef.current?.loadSession(sessionId, initialMessage), 100);
    };
    window.addEventListener("open-chat-session", handler);
    return () => window.removeEventListener("open-chat-session", handler);
  }, []);

  return (
    <div className="flex h-screen">
      <IconNav chatOpen={chatOpen} onToggleChat={() => setChatOpen(!chatOpen)} />

      {/* Main canvas */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>

      {/* Chat drawer */}
      <ChatDrawer ref={chatRef} open={chatOpen} onClose={() => setChatOpen(false)} />
    </div>
  );
}
