import { readFileSync, existsSync, readdirSync } from "fs";
import { join } from "path";
import { KNOWLEDGE_DIR } from "../paths.ts";

export function loadKnowledge(): string {
  const parts: string[] = [];

  // Always load skills.md
  const skillsPath = join(KNOWLEDGE_DIR, "skills.md");
  if (existsSync(skillsPath)) {
    parts.push(readFileSync(skillsPath, "utf-8"));
  }

  // Load overview.md (LLM-synthesized) if it exists
  const overviewPath = join(KNOWLEDGE_DIR, "overview.md");
  if (existsSync(overviewPath)) {
    parts.push(readFileSync(overviewPath, "utf-8"));
  }

  // Load company.md if it exists
  const companyPath = join(KNOWLEDGE_DIR, "company.md");
  if (existsSync(companyPath)) {
    parts.push(readFileSync(companyPath, "utf-8"));
  }

  // Load all repo knowledge files
  const reposDir = join(KNOWLEDGE_DIR, "repos");
  if (existsSync(reposDir)) {
    const repoFiles = readdirSync(reposDir).filter((f) => f.endsWith(".md"));
    for (const file of repoFiles) {
      const content = readFileSync(join(reposDir, file), "utf-8");
      if (content.trim()) {
        parts.push(content);
      }
    }
  }

  return parts.join("\n\n---\n\n");
}
