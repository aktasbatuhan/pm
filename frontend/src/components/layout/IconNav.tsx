import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  KanbanSquare,
  Lightbulb,
  Bot,
  BookOpen,
  Settings,
  MessageSquare,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface IconNavProps {
  chatOpen: boolean;
  onToggleChat: () => void;
}

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Overview" },
  { to: "/project", icon: KanbanSquare, label: "Project" },
  { to: "/insights", icon: Lightbulb, label: "Insights" },
  { to: "/agents", icon: Bot, label: "Agents" },
  { to: "/knowledge", icon: BookOpen, label: "Knowledge" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

export function IconNav({ chatOpen, onToggleChat }: IconNavProps) {
  return (
    <nav className="flex flex-col items-center w-12 border-r border-border bg-card py-3 gap-1 shrink-0">
      {/* Logo */}
      <div className="text-primary font-bold text-sm mb-4 tracking-wider">D</div>

      {/* Nav items */}
      <div className="flex flex-col gap-1 flex-1">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center justify-center w-9 h-9 rounded-md transition-colors group relative",
                isActive
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted"
              )
            }
            title={label}
          >
            <Icon size={18} strokeWidth={1.5} />
          </NavLink>
        ))}
      </div>

      {/* Chat toggle at bottom */}
      <button
        onClick={onToggleChat}
        className={cn(
          "flex items-center justify-center w-9 h-9 rounded-md transition-colors",
          chatOpen
            ? "bg-primary/15 text-primary"
            : "text-muted-foreground hover:text-foreground hover:bg-muted"
        )}
        title="Chat"
      >
        <MessageSquare size={18} strokeWidth={1.5} />
      </button>
    </nav>
  );
}
