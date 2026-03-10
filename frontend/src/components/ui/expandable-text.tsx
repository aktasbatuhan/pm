import { useState } from "react";
import { cn } from "@/lib/utils";
import { MarkdownContent } from "./markdown-content";

/**
 * Shows text collapsed to N lines with a "Show more" / "Show less" toggle.
 * Renders content as markdown when expanded.
 */
export function ExpandableText({
  content,
  collapsedLines = 4,
  className,
  alwaysMarkdown = false,
}: {
  content: string;
  collapsedLines?: number;
  className?: string;
  alwaysMarkdown?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);

  // Rough heuristic: if content has more lines or chars than what fits in collapsed view
  const needsExpansion = content.length > collapsedLines * 120 || content.split("\n").length > collapsedLines + 1;

  if (!needsExpansion && !alwaysMarkdown) {
    return <MarkdownContent content={content} className={className} />;
  }

  return (
    <div className={className}>
      {expanded ? (
        <MarkdownContent content={content} />
      ) : (
        <div
          className={cn("overflow-hidden relative")}
          style={{ maxHeight: `${collapsedLines * 1.5}rem` }}
        >
          <MarkdownContent content={content} />
          <div className="absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-card to-transparent" />
        </div>
      )}
      {needsExpansion && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-[10px] text-primary hover:text-primary/80 mt-1 transition-colors"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}
