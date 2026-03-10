import ReactMarkdown from "react-markdown";
import { cn } from "@/lib/utils";

/**
 * Renders markdown text with proper styling for the dark theme.
 * Used for synthesis summaries, escalation details, insight descriptions, etc.
 */
export function MarkdownContent({ content, className }: { content: string; className?: string }) {
  return (
    <div className={cn("markdown-content", className)}>
      <ReactMarkdown
        components={{
          h1: ({ children }) => <h1 className="text-sm font-bold text-foreground mt-3 mb-1.5">{children}</h1>,
          h2: ({ children }) => <h2 className="text-xs font-bold text-foreground mt-3 mb-1">{children}</h2>,
          h3: ({ children }) => <h3 className="text-xs font-semibold text-foreground mt-2 mb-1">{children}</h3>,
          p: ({ children }) => <p className="text-xs text-foreground/85 leading-relaxed mb-2 last:mb-0">{children}</p>,
          ul: ({ children }) => <ul className="text-xs text-foreground/85 list-disc pl-4 mb-2 space-y-0.5">{children}</ul>,
          ol: ({ children }) => <ol className="text-xs text-foreground/85 list-decimal pl-4 mb-2 space-y-0.5">{children}</ol>,
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
          em: ({ children }) => <em className="text-foreground/70">{children}</em>,
          code: ({ children }) => (
            <code className="text-[10px] bg-muted/50 text-primary/90 px-1 py-0.5 rounded font-mono">{children}</code>
          ),
          pre: ({ children }) => (
            <pre className="text-[10px] bg-muted/30 rounded p-2 overflow-x-auto mb-2 font-mono">{children}</pre>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-primary/30 pl-3 my-2 text-foreground/70">{children}</blockquote>
          ),
          hr: () => <hr className="border-border/50 my-3" />,
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
              {children}
            </a>
          ),
          table: ({ children }) => (
            <table className="w-full text-[10px] mb-2 border-collapse">{children}</table>
          ),
          thead: ({ children }) => <thead className="border-b border-border">{children}</thead>,
          th: ({ children }) => <th className="text-left py-1 px-1.5 text-muted-foreground font-normal">{children}</th>,
          td: ({ children }) => <td className="py-1 px-1.5 text-foreground border-t border-border/30">{children}</td>,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
