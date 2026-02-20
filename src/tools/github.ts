import { Octokit } from "@octokit/rest";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { z } from "zod/v4";
import {
  createSdkMcpServer,
  tool,
  type McpSdkServerConfigWithInstance,
} from "@anthropic-ai/claude-agent-sdk";

const execFileAsync = promisify(execFile);

function getOctokit() {
  const token = process.env.GITHUB_TOKEN;
  if (!token) throw new Error("GITHUB_TOKEN is not set");
  return new Octokit({ auth: token, userAgent: "pm-agent/0.1.0" });
}

function getGraphqlHeaders() {
  const token = process.env.GITHUB_TOKEN;
  if (!token) throw new Error("GITHUB_TOKEN is not set");
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
    "User-Agent": "pm-agent/0.1.0",
  };
}

async function graphql<T>(
  query: string,
  variables: Record<string, unknown> = {}
): Promise<T> {
  const response = await fetch("https://api.github.com/graphql", {
    method: "POST",
    headers: getGraphqlHeaders(),
    body: JSON.stringify({ query, variables }),
  });

  if (!response.ok) {
    throw new Error(
      `GitHub GraphQL error: ${response.status} ${response.statusText}`
    );
  }

  const json = (await response.json()) as {
    data?: T;
    errors?: Array<{ message: string }>;
  };

  if (json.errors?.length) {
    throw new Error(
      `GitHub GraphQL error: ${json.errors[0]?.message || "Unknown error"}`
    );
  }

  return json.data as T;
}

// --- Shared Project Items Fetcher (used by MCP tool + dashboard API) ---

export interface ProjectItem {
  title: string;
  number: number | null;
  state: string | null;
  status: string | null;
  priority: string | null;
  size: string | number | null;
  estimate: string | number | null;
  repository: string | null;
  issue_url: string | null;
  assignees: string[];
  custom_fields: Record<string, string | number | null>;
}

export async function fetchProjectItems(owner: string, projectNumber: number): Promise<ProjectItem[]> {
  const query_str = `
    query($owner: String!, $projectNumber: Int!, $cursor: String) {
      organization(login: $owner) {
        projectV2(number: $projectNumber) {
          items(first: 100, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            nodes {
              content {
                ... on Issue {
                  title
                  url
                  number
                  state
                  repository { name }
                  assignees(first: 5) { nodes { login } }
                }
                ... on PullRequest {
                  title
                  url
                  number
                  state
                  repository { name }
                }
                ... on DraftIssue { title }
              }
              fieldValues(first: 15) {
                nodes {
                  ... on ProjectV2ItemFieldSingleSelectValue {
                    field { ... on ProjectV2SingleSelectField { name } }
                    name
                  }
                  ... on ProjectV2ItemFieldNumberValue {
                    field { ... on ProjectV2Field { name } }
                    number
                  }
                  ... on ProjectV2ItemFieldIterationValue {
                    field { ... on ProjectV2IterationField { name } }
                    title
                  }
                  ... on ProjectV2ItemFieldTextValue {
                    field { ... on ProjectV2Field { name } }
                    text
                  }
                }
              }
            }
          }
        }
      }
    }
  `;

  interface GQLResponse {
    organization: {
      projectV2: {
        items: {
          pageInfo: { hasNextPage: boolean; endCursor: string | null };
          nodes: Array<{
            content: {
              title?: string;
              url?: string;
              number?: number;
              state?: string;
              repository?: { name: string };
              assignees?: { nodes: Array<{ login: string }> };
            } | null;
            fieldValues: {
              nodes: Array<{
                field?: { name: string };
                name?: string;
                number?: number;
                title?: string;
                text?: string;
              }>;
            };
          }>;
        };
      };
    };
  }

  const items: ProjectItem[] = [];
  let cursor: string | null = null;

  while (true) {
    const result: GQLResponse = await graphql<GQLResponse>(query_str, {
      owner,
      projectNumber,
      cursor,
    });

    const projectItems = result.organization.projectV2.items;

    for (const node of projectItems.nodes) {
      if (!node.content) continue;

      const fields: Record<string, string | number | null> = {};
      for (const fv of node.fieldValues.nodes) {
        if (fv.field?.name) {
          fields[fv.field.name.toLowerCase()] =
            fv.name ?? fv.number ?? fv.title ?? fv.text ?? null;
        }
      }

      const { status, priority, size, estimate, ...customFields } = fields;

      items.push({
        title: node.content.title || "Untitled",
        number: node.content.number ?? null,
        state: node.content.state ?? null,
        status: (status as string) ?? null,
        priority: (priority as string) ?? null,
        size: size ?? null,
        estimate: estimate ?? null,
        repository: node.content.repository?.name || null,
        issue_url: node.content.url || null,
        assignees:
          node.content.assignees?.nodes.map((a: { login: string }) => a.login) ?? [],
        custom_fields: customFields,
      });
    }

    if (!projectItems.pageInfo.hasNextPage) break;
    cursor = projectItems.pageInfo.endCursor;
  }

  return items;
}

export interface ActivityItem {
  type: "pr" | "commit";
  title: string;
  author: string;
  repo: string;
  url: string;
  status?: string;
  createdAt: string;
}

export async function fetchRecentActivity(
  org: string,
  repos: string[],
  limit: number = 20,
): Promise<ActivityItem[]> {
  const octokit = getOctokit();
  const activities: ActivityItem[] = [];
  const perRepo = Math.max(5, Math.ceil(limit / repos.length));

  await Promise.all(
    repos.slice(0, 10).map(async (repo) => {
      try {
        const { data: prs } = await octokit.rest.pulls.list({
          owner: org,
          repo,
          state: "all",
          sort: "updated",
          direction: "desc",
          per_page: perRepo,
        });

        for (const pr of prs) {
          activities.push({
            type: "pr",
            title: pr.title,
            author: pr.user?.login || "unknown",
            repo,
            url: pr.html_url,
            status: pr.merged_at ? "merged" : pr.state,
            createdAt: pr.updated_at || pr.created_at,
          });
        }

        const { data: commits } = await octokit.rest.repos.listCommits({
          owner: org,
          repo,
          per_page: perRepo,
        });

        for (const commit of commits) {
          activities.push({
            type: "commit",
            title: (commit.commit.message ?? "").split("\n")[0] ?? "",
            author: commit.author?.login || commit.commit.author?.name || "unknown",
            repo,
            url: commit.html_url,
            createdAt: commit.commit.author?.date || "",
          });
        }
      } catch {
        // Skip repos that fail (permissions, empty, etc.)
      }
    }),
  );

  activities.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
  return activities.slice(0, limit);
}

// --- MCP Tools ---

const listProjectItemsTool = tool(
  "github_list_project_items",
  "List items from a GitHub Project v2 with all field values (status, priority, size, sprint, etc.)",
  {
    owner: z.string().describe("Organization that owns the project"),
    project_number: z.number().describe("The project number"),
  },
  async ({ owner, project_number }) => {
    const items = await fetchProjectItems(owner, project_number);
    const summary = `TOTAL ITEMS RETURNED: ${items.length}\n\n`;
    return { content: [{ type: "text" as const, text: summary + JSON.stringify(items, null, 2) }] };
  },
  { annotations: { readOnly: true } }
);

const listProjectFieldsTool = tool(
  "github_list_project_fields",
  "List all custom fields configured on a GitHub Project V2 board. Returns field names, types, options (for single-select), and iterations (for iteration/sprint fields). Use this to discover what fields exist and their possible values before filtering project items.",
  {
    owner: z.string().describe("GitHub organization or user that owns the project"),
    project_number: z.number().describe("The project number"),
  },
  async ({ owner, project_number }) => {
    const query_str = `
      query($owner: String!, $projectNumber: Int!) {
        organization(login: $owner) {
          projectV2(number: $projectNumber) {
            title
            fields(first: 50) {
              nodes {
                ... on ProjectV2Field {
                  name
                  dataType
                }
                ... on ProjectV2SingleSelectField {
                  name
                  dataType
                  options { id name }
                }
                ... on ProjectV2IterationField {
                  name
                  dataType
                  configuration {
                    iterations { title startDate duration }
                    completedIterations { title startDate duration }
                  }
                }
              }
            }
          }
        }
      }
    `;

    interface FieldNode {
      name: string;
      dataType: string;
      options?: Array<{ id: string; name: string }>;
      configuration?: {
        iterations: Array<{ title: string; startDate: string; duration: number }>;
        completedIterations: Array<{ title: string; startDate: string; duration: number }>;
      };
    }

    interface GQLResponse {
      organization: {
        projectV2: {
          title: string;
          fields: { nodes: FieldNode[] };
        };
      };
    }

    const result = await graphql<GQLResponse>(query_str, {
      owner,
      projectNumber: project_number,
    });

    const project = result.organization.projectV2;
    const fields = project.fields.nodes.map((f) => {
      const field: Record<string, unknown> = {
        name: f.name,
        type: f.dataType,
      };
      if (f.options) {
        field.options = f.options.map((o) => o.name);
      }
      if (f.configuration) {
        field.active_iterations = f.configuration.iterations.map((i) => ({
          title: i.title,
          start_date: i.startDate,
          duration_days: i.duration,
        }));
        field.completed_iterations = f.configuration.completedIterations.map((i) => ({
          title: i.title,
          start_date: i.startDate,
          duration_days: i.duration,
        }));
      }
      return field;
    });

    return {
      content: [{
        type: "text" as const,
        text: JSON.stringify({ project_title: project.title, fields }, null, 2),
      }],
    };
  },
  { annotations: { readOnly: true } }
);

// --- GitHub CLI Tool ---

function parseCommandArgs(command: string): string[] {
  const args: string[] = [];
  let current = "";
  let inQuote = false;
  let quoteChar = "";

  for (const char of command) {
    if (!inQuote && (char === '"' || char === "'")) {
      inQuote = true;
      quoteChar = char;
    } else if (inQuote && char === quoteChar) {
      inQuote = false;
    } else if (!inQuote && char === " ") {
      if (current) args.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  if (current) args.push(current);
  return args;
}

const githubCliTool = tool(
  "github_cli",
  `Execute a GitHub CLI (gh) command. Authenticated with the project's GitHub token.
This is the primary tool for all GitHub operations: issues, PRs, repos, code, workflows, and raw API calls.

Common commands:
- issue list --repo owner/repo --json number,title,state,assignees
- issue view 123 --repo owner/repo --json title,body,comments
- issue create --repo owner/repo --title "Title" --body "Body"
- issue edit 123 --repo owner/repo --add-label "bug"
- issue comment 123 --repo owner/repo --body "Comment text"
- pr list --repo owner/repo --json number,title,state,author
- pr view 123 --repo owner/repo --json title,body,files,reviews,comments
- pr create --repo owner/repo --title "Title" --body "Body" --base main --head branch
- pr review 123 --repo owner/repo --comment --body "Review"
- pr merge 123 --repo owner/repo --squash
- repo list owner --json name,description,language
- repo view owner/repo --json name,description,defaultBranchRef
- api repos/owner/repo/contents/path (read file via REST API)
- api repos/owner/repo/readme --jq '.content' (get README base64)
- workflow list --repo owner/repo
- workflow run ci.yml --repo owner/repo
- repo clone owner/repo /tmp/repo (clone for multi-file operations)

For multi-file code changes: clone the repo, make changes with git, push, then create a PR.`,
  {
    command: z.string().describe("The gh command to execute (without the 'gh' prefix). Example: 'pr list --repo owner/repo --json number,title,state'"),
  },
  async ({ command }) => {
    const args = parseCommandArgs(command);
    if (args.length === 0) {
      return {
        content: [{ type: "text" as const, text: "Error: Empty command" }],
        isError: true,
      };
    }

    try {
      const { stdout, stderr } = await execFileAsync("gh", args, {
        env: { ...process.env, GH_TOKEN: process.env.GITHUB_TOKEN },
        timeout: 120000,
        maxBuffer: 5 * 1024 * 1024,
        cwd: "/tmp",
      });

      const output = (stdout + stderr).trim();
      return {
        content: [{ type: "text" as const, text: output || "(no output)" }],
      };
    } catch (error: unknown) {
      const err = error as { stderr?: string; message?: string };
      return {
        content: [{ type: "text" as const, text: `Error: ${err.stderr || err.message}` }],
        isError: true,
      };
    }
  },
  { annotations: { readOnly: false, destructive: false } }
);

// --- Export MCP Server ---

const READ_TOOLS = [listProjectItemsTool, listProjectFieldsTool];
const WRITE_TOOLS = [githubCliTool];

export const WRITE_TOOL_NAMES = WRITE_TOOLS.map((t) => t.name);

export function createGitHubMcpServer(): McpSdkServerConfigWithInstance {
  return createSdkMcpServer({
    name: "github",
    version: "0.1.0",
    tools: [...READ_TOOLS, ...WRITE_TOOLS],
  });
}
