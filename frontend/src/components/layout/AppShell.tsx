import { useState } from "react";
import { Outlet } from "react-router-dom";
import { IconNav } from "./IconNav";
import { ChatDrawer } from "./ChatDrawer";

export function AppShell() {
  const [chatOpen, setChatOpen] = useState(false);

  return (
    <div className="flex h-screen">
      <IconNav chatOpen={chatOpen} onToggleChat={() => setChatOpen(!chatOpen)} />

      {/* Main canvas */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>

      {/* Chat drawer */}
      <ChatDrawer open={chatOpen} onClose={() => setChatOpen(false)} />
    </div>
  );
}
