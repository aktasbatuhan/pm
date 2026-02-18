/**
 * Convert GitHub Flavored Markdown to Slack mrkdwn format.
 */
export function toSlackMarkdown(gfm: string): string {
  let text = gfm;

  // Preserve code blocks from conversion
  const codeBlocks: string[] = [];
  text = text.replace(/```[\s\S]*?```/g, (match) => {
    codeBlocks.push(match);
    return `__CODEBLOCK_${codeBlocks.length - 1}__`;
  });

  // Preserve inline code
  const inlineCode: string[] = [];
  text = text.replace(/`[^`]+`/g, (match) => {
    inlineCode.push(match);
    return `__INLINE_${inlineCode.length - 1}__`;
  });

  // Convert tables to monospace code blocks
  text = convertTables(text);

  // Headers: ## Heading -> *Heading*
  text = text.replace(/^#{1,6}\s+(.+)$/gm, "*$1*");

  // Bold: **text** -> *text*
  text = text.replace(/\*\*(.+?)\*\*/g, "*$1*");

  // Italic: single underscore already works in Slack (_text_)
  // Handle *italic* (single asterisk, not bold) — but only after bold conversion
  // This is tricky because *text* in GFM is italic but in Slack mrkdwn is bold
  // After bold conversion, remaining single *text* should become _text_
  // Skip this — Slack treats *text* as bold which is close enough

  // Strikethrough: ~~text~~ -> ~text~
  text = text.replace(/~~(.+?)~~/g, "~$1~");

  // Images: ![alt](url) -> <url|alt> (before links)
  text = text.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, "<$2|$1>");

  // Links: [text](url) -> <url|text>
  text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, "<$2|$1>");

  // Horizontal rules
  text = text.replace(/^[-*_]{3,}$/gm, "───────────────────────");

  // Restore code blocks and inline code
  text = text.replace(/__CODEBLOCK_(\d+)__/g, (_match, i: string) => codeBlocks[parseInt(i)] ?? "");
  text = text.replace(/__INLINE_(\d+)__/g, (_match, i: string) => inlineCode[parseInt(i)] ?? "");

  return text;
}

/**
 * Convert markdown tables to monospace text blocks for Slack.
 */
function convertTables(text: string): string {
  const lines = text.split("\n");
  const result: string[] = [];
  let tableLines: string[] = [];
  let inTable = false;

  for (const line of lines) {
    const isTableRow = /^\|(.+)\|$/.test(line.trim());
    const isSeparator = /^\|[-:\s|]+\|$/.test(line.trim());

    if (isTableRow || isSeparator) {
      if (!inTable) inTable = true;
      if (!isSeparator) {
        tableLines.push(line.trim());
      }
    } else {
      if (inTable) {
        result.push(formatTable(tableLines));
        tableLines = [];
        inTable = false;
      }
      result.push(line);
    }
  }

  if (inTable) {
    result.push(formatTable(tableLines));
  }

  return result.join("\n");
}

/**
 * Format table rows as a monospace code block.
 */
function formatTable(rows: string[]): string {
  if (rows.length === 0) return "";

  const parsed = rows.map((row) =>
    row
      .split("|")
      .slice(1, -1)
      .map((cell) => cell.trim())
  );

  // Calculate column widths
  const colWidths: number[] = [];
  for (const row of parsed) {
    row.forEach((cell, i) => {
      colWidths[i] = Math.max(colWidths[i] || 0, cell.length);
    });
  }

  // Format rows with padding
  const formatted = parsed.map((row) =>
    row.map((cell, i) => cell.padEnd(colWidths[i] || 0)).join("  ")
  );

  return "```\n" + formatted.join("\n") + "\n```";
}

/**
 * Split a message that exceeds Slack's character limit.
 * Splits at paragraph boundaries, then line boundaries.
 */
export function splitMessage(text: string, maxLen: number = 3900): string[] {
  if (text.length <= maxLen) return [text];

  const chunks: string[] = [];
  let remaining = text;

  while (remaining.length > 0) {
    if (remaining.length <= maxLen) {
      chunks.push(remaining);
      break;
    }

    // Try paragraph boundary
    let splitIdx = remaining.lastIndexOf("\n\n", maxLen);
    if (splitIdx < maxLen * 0.3) {
      // Try line boundary
      splitIdx = remaining.lastIndexOf("\n", maxLen);
    }
    if (splitIdx < maxLen * 0.3) {
      // Hard cut
      splitIdx = maxLen;
    }

    chunks.push(remaining.slice(0, splitIdx));
    remaining = remaining.slice(splitIdx).trimStart();
  }

  return chunks;
}
