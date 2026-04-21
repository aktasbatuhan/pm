"use client";

import { memo, useMemo } from "react";
import { Response } from "@/components/ui/response";
import { ArtifactRenderer } from "@/components/artifact-renderer";

/**
 * Enhanced Response component that:
 * 1. Wraps markdown in Tailwind Typography prose classes
 * 2. Extracts ```react-chart blocks and renders as live artifacts
 */

interface ArtifactBlock {
  type: "artifact";
  code: string;
  title: string;
}

interface TextBlock {
  type: "text";
  content: string;
}

type Block = ArtifactBlock | TextBlock;

function parseBlocks(content: string): Block[] {
  const blocks: Block[] = [];
  const regex = /```(?:react-chart|chart)(?:\s+title="([^"]*)")?\s*\n([\s\S]*?)```/g;
  let lastIndex = 0;

  for (const match of content.matchAll(regex)) {
    const before = content.slice(lastIndex, match.index);
    if (before.trim()) {
      blocks.push({ type: "text", content: before });
    }
    blocks.push({
      type: "artifact",
      code: match[2].trim(),
      title: match[1] || "Chart",
    });
    lastIndex = match.index! + match[0].length;
  }

  const after = content.slice(lastIndex);
  if (after.trim()) {
    blocks.push({ type: "text", content: after });
  }

  return blocks;
}

function ProseResponse({ children }: { children: string }) {
  return (
    <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none prose-headings:tracking-tight prose-h1:text-lg prose-h2:text-base prose-h2:font-semibold prose-h3:text-sm prose-h3:font-semibold prose-p:leading-relaxed prose-li:leading-relaxed prose-code:rounded prose-code:bg-muted prose-code:px-1.5 prose-code:py-0.5 prose-code:text-[13px] prose-code:before:content-none prose-code:after:content-none prose-pre:bg-zinc-950 prose-pre:text-zinc-100 prose-a:text-primary prose-a:no-underline hover:prose-a:underline">
      <Response>{children}</Response>
    </div>
  );
}

interface Props {
  children: string;
}

export const RichResponse = memo(function RichResponse({ children }: Props) {
  const blocks = useMemo(() => parseBlocks(children), [children]);

  if (blocks.length === 1 && blocks[0].type === "text") {
    return <ProseResponse>{children}</ProseResponse>;
  }

  return (
    <div>
      {blocks.map((block, i) =>
        block.type === "text" ? (
          <ProseResponse key={i}>{block.content}</ProseResponse>
        ) : (
          <ArtifactRenderer key={i} code={block.code} title={block.title} />
        )
      )}
    </div>
  );
});
