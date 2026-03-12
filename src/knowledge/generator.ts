import { Octokit } from "@octokit/rest";
import { writeFileSync, mkdirSync, existsSync } from "fs";
import { join } from "path";
import { KNOWLEDGE_DIR } from "../paths.ts";

function getOctokit() {
  return new Octokit({
    auth: process.env.GITHUB_TOKEN,
    userAgent: "pm-agent/0.1.0",
  });
}

// --- LLM helper ---

const DEFAULT_MODEL = process.env.AGENT_MODEL || "minimax/minimax-m2.5";

async function callLLM(system: string, user: string): Promise<string> {
  // Prefer OpenRouter when available (supports all model providers)
  if (process.env.OPENROUTER_API_KEY) {
    const res = await fetch("https://openrouter.ai/api/v1/chat/completions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${process.env.OPENROUTER_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: DEFAULT_MODEL,
        messages: [
          { role: "system", content: system },
          { role: "user", content: user },
        ],
        max_tokens: 4096,
      }),
    });
    const json = (await res.json()) as {
      choices: { message: { content: string } }[];
    };
    return json.choices[0].message.content;
  }

  // Anthropic direct fallback
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "x-api-key": process.env.ANTHROPIC_API_KEY || "",
      "anthropic-version": "2023-06-01",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: process.env.ANTHROPIC_MODEL || "google/gemini-3-flash-preview",
      max_tokens: 4096,
      system,
      messages: [{ role: "user", content: user }],
    }),
  });
  const json = (await res.json()) as {
    content: { text: string }[];
  };
  return json.content[0].text;
}

// --- Raw data types ---

interface RawRepoData {
  name: string;
  description: string;
  language: string;
  defaultBranch: string;
  topics: string[];
  readme: string;
  contributors: { login: string; contributions: number }[];
  recentPRs: {
    title: string;
    author: string;
    mergedAt: string;
    labels: string[];
  }[];
  recentIssues: {
    title: string;
    labels: string[];
    assignees: string[];
    state: string;
    createdAt: string;
  }[];
}

interface OrgData {
  name: string;
  description: string;
  website: string;
  repoSummaries: {
    name: string;
    description: string;
    language: string;
    openIssues: number;
    stars: number;
  }[];
}

// --- Phase 1: Collect raw data ---

async function collectOrgData(org: string): Promise<OrgData> {
  const octokit = getOctokit();

  let orgInfo = { name: org, description: "", website: "" };
  try {
    const { data } = await octokit.rest.orgs.get({ org });
    orgInfo = {
      name: data.name || org,
      description: data.description || "",
      website: data.blog || "",
    };
  } catch {
    // Use defaults
  }

  const { data: repos } = await octokit.rest.repos.listForOrg({
    org,
    per_page: 50,
    sort: "updated",
  });

  return {
    ...orgInfo,
    repoSummaries: repos.map((r) => ({
      name: r.name,
      description: r.description || "",
      language: r.language || "unknown",
      openIssues: r.open_issues_count,
      stars: r.stargazers_count,
    })),
  };
}

async function collectRepoData(
  owner: string,
  repo: string
): Promise<RawRepoData> {
  const octokit = getOctokit();

  const { data: repoData } = await octokit.rest.repos.get({ owner, repo });

  // README (up to 5000 chars)
  let readme = "";
  try {
    const { data } = await octokit.rest.repos.getContent({
      owner,
      repo,
      path: "README.md",
    });
    if ("content" in data && data.content) {
      const full = Buffer.from(data.content, "base64").toString("utf-8");
      readme = full.slice(0, 5000);
      if (full.length > 5000) readme += "\n...(truncated)";
    }
  } catch {
    readme = "";
  }

  // Contributors
  let contributors: { login: string; contributions: number }[] = [];
  try {
    const { data } = await octokit.rest.repos.listContributors({
      owner,
      repo,
      per_page: 10,
    });
    contributors = data
      .filter((c) => c.login && !c.login.includes("[bot]"))
      .map((c) => ({
        login: c.login!,
        contributions: c.contributions,
      }));
  } catch {
    /* empty */
  }

  // Recent merged PRs
  let recentPRs: RawRepoData["recentPRs"] = [];
  try {
    const { data } = await octokit.rest.pulls.list({
      owner,
      repo,
      state: "closed",
      sort: "updated",
      direction: "desc",
      per_page: 15,
    });
    recentPRs = data
      .filter((pr) => pr.merged_at)
      .slice(0, 10)
      .map((pr) => ({
        title: pr.title,
        author: pr.user?.login || "unknown",
        mergedAt: pr.merged_at || "",
        labels: pr.labels.map((l) => l.name || ""),
      }));
  } catch {
    /* empty */
  }

  // Recent issues
  let recentIssues: RawRepoData["recentIssues"] = [];
  try {
    const { data } = await octokit.rest.issues.listForRepo({
      owner,
      repo,
      state: "all",
      sort: "updated",
      direction: "desc",
      per_page: 15,
    });
    recentIssues = data
      .filter((i) => !i.pull_request) // Exclude PRs
      .slice(0, 10)
      .map((i) => ({
        title: i.title,
        labels: i.labels
          .map((l) => (typeof l === "string" ? l : l.name || ""))
          .filter(Boolean),
        assignees: i.assignees?.map((a) => a.login) || [],
        state: i.state,
        createdAt: i.created_at,
      }));
  } catch {
    /* empty */
  }

  return {
    name: repo,
    description: repoData.description || "",
    language: repoData.language || "Unknown",
    defaultBranch: repoData.default_branch,
    topics: repoData.topics || [],
    readme,
    contributors,
    recentPRs,
    recentIssues,
  };
}

// --- Phase 2: LLM synthesis ---

const OVERVIEW_SYSTEM = `You are a technical analyst writing an internal knowledge document for a PM agent.
Given raw GitHub data from an organization, produce a comprehensive overview in markdown.
Be specific and factual — only use information from the provided data. Do not invent details.
Write in a dense, informative style. No fluff. Use tables where appropriate.`;

async function synthesizeOverview(
  org: OrgData,
  repos: RawRepoData[]
): Promise<string> {
  // Build a compact data dump for the LLM
  const repoSummaries = repos
    .map(
      (r) =>
        `## ${r.name}\n- ${r.description || "No description"}\n- Language: ${r.language}\n- Contributors: ${r.contributors.map((c) => `@${c.login}(${c.contributions})`).join(", ")}\n- Recent PRs: ${r.recentPRs.map((p) => p.title).join("; ") || "none"}\n- Recent Issues: ${r.recentIssues.map((i) => `${i.title} [${i.state}]`).join("; ") || "none"}\n- Topics: ${r.topics.join(", ") || "none"}`
    )
    .join("\n\n");

  // Collect all unique team members
  const teamMap = new Map<string, { repos: string[]; total: number }>();
  for (const r of repos) {
    for (const c of r.contributors) {
      if (!teamMap.has(c.login)) {
        teamMap.set(c.login, { repos: [], total: 0 });
      }
      const entry = teamMap.get(c.login)!;
      entry.repos.push(r.name);
      entry.total += c.contributions;
    }
  }

  const teamSection = [...teamMap.entries()]
    .sort((a, b) => b[1].total - a[1].total)
    .map(
      ([login, info]) =>
        `@${login}: ${info.total} contributions across ${info.repos.join(", ")}`
    )
    .join("\n");

  const allRepoList = org.repoSummaries
    .map(
      (r) =>
        `${r.name} | ${r.language} | ${r.description || "-"} | ${r.openIssues} issues`
    )
    .join("\n");

  const prompt = `Here is raw data from the GitHub organization "${org.name}".

## Organization
- Name: ${org.name}
- Description: ${org.description}
- Website: ${org.website}

## All Repositories (${org.repoSummaries.length} total)
${allRepoList}

## Detailed Repository Data (project-related repos)
${repoSummaries}

## Team Members (by contribution count)
${teamSection}

---

Generate a comprehensive knowledge document with these sections:

1. **Company Overview** — What does this org do? What's their product? (Infer from repos + descriptions)

2. **Architecture** — How do the repositories connect? What's the system architecture? Identify:
   - Frontend vs backend vs infrastructure repos
   - Shared libraries/tools
   - Data flow between services
   - Deployment patterns (look for Docker, CI, deploy dirs)

3. **Tech Stack** — A table of technologies used across the org. Group by category (languages, frameworks, databases, infrastructure).

4. **Team** — Who works on what? Identify:
   - Core contributors per repo area
   - Who spans multiple repos (senior/lead signal)
   - Team size and structure

5. **Active Focus Areas** — What's the team working on right now? Analyze recent PRs and issues to identify current priorities and themes.

6. **Repository Map** — A table of all repos with: name, purpose (1 line), language, key contributors, relationship to other repos.

Output clean markdown. Be specific. Use the actual data provided.`;

  return await callLLM(OVERVIEW_SYSTEM, prompt);
}

const REPO_SYSTEM = `You are a technical analyst writing an internal knowledge document about a specific repository.
Given raw GitHub data, produce a detailed knowledge file that would help a PM agent understand this repo deeply.
Be specific and factual. No fluff. Use tables where appropriate.`;

async function synthesizeRepoKnowledge(
  repo: RawRepoData,
  orgContext: string
): Promise<string> {
  const prs = repo.recentPRs.length
    ? repo.recentPRs
        .map((p) => `- "${p.title}" by @${p.author} (merged ${p.mergedAt.split("T")[0]})`)
        .join("\n")
    : "No recent PRs";

  const issues = repo.recentIssues.length
    ? repo.recentIssues
        .map(
          (i) =>
            `- "${i.title}" [${i.state}] labels:[${i.labels.join(",")}] assigned:[${i.assignees.join(",")}]`
        )
        .join("\n")
    : "No recent issues";

  const contribs = repo.contributors.length
    ? repo.contributors
        .map((c) => `@${c.login}: ${c.contributions} contributions`)
        .join("\n")
    : "Unknown";

  const prompt = `Repository: ${repo.name}
Organization context: ${orgContext}

## Raw Data

**Description**: ${repo.description || "None"}
**Language**: ${repo.language}
**Default branch**: ${repo.defaultBranch}
**Topics**: ${repo.topics.join(", ") || "None"}

### README
${repo.readme || "No README"}

### Contributors
${contribs}

### Recent Merged PRs
${prs}

### Recent Issues
${issues}

---

Generate a knowledge document with these sections:

1. **Purpose** — What this repo does, in 2-3 sentences. Be specific about its role in the system.

2. **Tech Stack & Patterns** — Based on README and metadata:
   - Framework/tech choices
   - Key patterns mentioned
   - How to run / develop locally

3. **Dependencies & Relationships** — How this repo connects to others in the org. Infer from naming, descriptions, README mentions.

4. **Team & Ownership** — Who are the main contributors? Who appears most active recently (from PRs)?

5. **Recent Activity** — What's been happening? Analyze PRs and issues to identify:
   - Current development themes
   - Open problems/blockers
   - Recent completions

Note: The PM agent has live GitHub tools to explore directories, files, and code at runtime. This document should focus on high-level understanding, not file-level details.

Output clean markdown starting with a level-1 heading of the repo name.`;

  return await callLLM(REPO_SYSTEM, prompt);
}

// --- Public API ---

/**
 * Quick company index — no LLM, just GitHub API.
 * Kept for fast reference even without LLM keys.
 */
export async function generateCompanyKnowledge(org: string): Promise<string> {
  const orgData = await collectOrgData(org);

  const repoList = orgData.repoSummaries
    .map(
      (r) =>
        `| ${r.name} | ${r.language} | ${r.description || "-"} | ${r.openIssues} |`
    )
    .join("\n");

  const content = `# ${orgData.name}

${orgData.description}

- **GitHub**: ${org}
${orgData.website ? `- **Website**: ${orgData.website}` : ""}

## Repositories

| Repository | Language | Description | Open Issues |
|:-----------|:---------|:------------|:------------|
${repoList}
`;

  if (!existsSync(KNOWLEDGE_DIR)) mkdirSync(KNOWLEDGE_DIR, { recursive: true });
  writeFileSync(join(KNOWLEDGE_DIR, "company.md"), content);
  return content;
}

/**
 * Generate a single repo knowledge file (non-LLM fallback).
 */
export async function generateRepoKnowledge(
  owner: string,
  repo: string
): Promise<string> {
  const data = await collectRepoData(owner, repo);

  const content = `# ${repo}

${data.description || "No description"}

- Language: ${data.language}
- Branch: ${data.defaultBranch}
- Topics: ${data.topics.join(", ") || "None"}
- Contributors: ${data.contributors.map((c) => `@${c.login}(${c.contributions})`).join(", ")}

## Recent PRs
${data.recentPRs.map((p) => `- ${p.title} (@${p.author})`).join("\n") || "None"}

## Recent Issues
${data.recentIssues.map((i) => `- ${i.title} [${i.state}]`).join("\n") || "None"}
`;

  const reposDir = join(KNOWLEDGE_DIR, "repos");
  if (!existsSync(reposDir)) mkdirSync(reposDir, { recursive: true });
  writeFileSync(join(reposDir, `${repo}.md`), content);
  return content;
}

/**
 * Full LLM-powered knowledge generation.
 * Collects rich data from GitHub, then synthesizes with Claude.
 */
export async function generateFullKnowledge(
  org: string,
  repoNames: string[],
  onProgress?: (msg: string) => void | Promise<void>
): Promise<void> {
  if (!existsSync(KNOWLEDGE_DIR)) mkdirSync(KNOWLEDGE_DIR, { recursive: true });

  // Phase 1: Collect data
  await onProgress?.("Collecting organization data...");
  const orgData = await collectOrgData(org);

  await onProgress?.(`Collecting data for ${repoNames.length} repositories...`);
  const repoDataMap: RawRepoData[] = [];
  for (const repo of repoNames) {
    await onProgress?.(`Fetching ${repo}...`);
    try {
      const data = await collectRepoData(org, repo);
      repoDataMap.push(data);
    } catch (err) {
      await onProgress?.(
        `Skipped ${repo}: ${err instanceof Error ? err.message : String(err)}`
      );
    }
  }

  // Write company.md (non-LLM, fast reference)
  await onProgress?.("Writing company.md...");
  await generateCompanyKnowledge(org);

  // Phase 2: LLM synthesis
  const hasLLMKey =
    !!process.env.ANTHROPIC_API_KEY || !!process.env.OPENROUTER_API_KEY;

  if (!hasLLMKey) {
    await onProgress?.(
      "No LLM API key found — writing raw knowledge files (no synthesis)"
    );
    for (const data of repoDataMap) {
      await generateRepoKnowledge(org, data.name);
      await onProgress?.(`repos/${data.name}.md written (raw)`);
    }
    return;
  }

  // Generate overview.md
  await onProgress?.("Synthesizing overview with Claude...");
  try {
    const overview = await synthesizeOverview(orgData, repoDataMap);
    writeFileSync(join(KNOWLEDGE_DIR, "overview.md"), overview);
    await onProgress?.("overview.md generated");
  } catch (err) {
    await onProgress?.(
      `overview.md failed: ${err instanceof Error ? err.message : String(err)}`
    );
  }

  // Generate per-repo knowledge (run in parallel, 3 at a time)
  const orgContext = `${orgData.name}: ${orgData.description}. Repos: ${orgData.repoSummaries.map((r) => r.name).join(", ")}`;
  const reposDir = join(KNOWLEDGE_DIR, "repos");
  if (!existsSync(reposDir)) mkdirSync(reposDir, { recursive: true });

  const batchSize = 3;
  for (let i = 0; i < repoDataMap.length; i += batchSize) {
    const batch = repoDataMap.slice(i, i + batchSize);
    const results = await Promise.allSettled(
      batch.map(async (repo) => {
        await onProgress?.(`Synthesizing ${repo.name}...`);
        const content = await synthesizeRepoKnowledge(repo, orgContext);
        writeFileSync(join(reposDir, `${repo.name}.md`), content);
        await onProgress?.(`repos/${repo.name}.md generated`);
      })
    );
    for (const r of results) {
      if (r.status === "rejected") {
        await onProgress?.(`Failed: ${r.reason}`);
      }
    }
  }

  await onProgress?.("Knowledge generation complete");
}
