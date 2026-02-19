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

// --- Read Tools ---

const listReposTool = tool(
  "github_list_repos",
  "List repositories for a GitHub organization",
  { org: z.string().describe("The GitHub organization name") },
  async ({ org }) => {
    const octokit = getOctokit();
    const repos: Array<{
      name: string;
      description: string | null;
      language: string | null;
      updated_at: string;
      open_issues_count: number;
    }> = [];
    let page = 1;

    while (true) {
      const { data } = await octokit.rest.repos.listForOrg({
        org,
        per_page: 100,
        page,
        sort: "updated",
      });
      for (const repo of data) {
        repos.push({
          name: repo.name,
          description: repo.description ?? null,
          language: repo.language ?? null,
          updated_at: repo.updated_at || "",
          open_issues_count: repo.open_issues_count ?? 0,
        });
      }
      if (data.length < 100) break;
      page++;
    }

    return { content: [{ type: "text" as const, text: JSON.stringify(repos, null, 2) }] };
  },
  { annotations: { readOnly: true } }
);

const getRepoTool = tool(
  "github_get_repo",
  "Get detailed information about a specific repository",
  {
    owner: z.string().describe("Repository owner (user or org)"),
    repo: z.string().describe("Repository name"),
  },
  async ({ owner, repo }) => {
    const octokit = getOctokit();
    const { data } = await octokit.rest.repos.get({ owner, repo });
    const result = {
      name: data.name,
      description: data.description,
      language: data.language,
      default_branch: data.default_branch,
      topics: data.topics || [],
      open_issues_count: data.open_issues_count,
      stars: data.stargazers_count,
    };
    return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
  },
  { annotations: { readOnly: true } }
);

const listIssuesTool = tool(
  "github_list_issues",
  "List issues for a repository with optional filters",
  {
    owner: z.string().describe("Repository owner"),
    repo: z.string().describe("Repository name"),
    state: z
      .enum(["open", "closed", "all"])
      .optional()
      .describe("Filter by state (default: open)"),
    labels: z
      .string()
      .optional()
      .describe("Comma-separated label names to filter by"),
    limit: z
      .number()
      .optional()
      .describe("Maximum number of issues to return (default: 100)"),
  },
  async ({ owner, repo, state, labels, limit }) => {
    const octokit = getOctokit();
    const maxResults = limit ?? 100;
    const issues: Array<{
      number: number;
      title: string;
      state: string;
      assignees: string[];
      labels: string[];
      created_at: string;
      updated_at: string;
    }> = [];
    let page = 1;

    while (issues.length < maxResults) {
      const { data } = await octokit.rest.issues.listForRepo({
        owner,
        repo,
        state: state ?? "open",
        labels,
        per_page: Math.min(100, maxResults - issues.length),
        page,
      });

      for (const issue of data) {
        if (issue.pull_request) continue;
        issues.push({
          number: issue.number,
          title: issue.title,
          state: issue.state,
          assignees: issue.assignees?.map((a) => a.login) || [],
          labels: issue.labels
            .map((l) => (typeof l === "string" ? l : l.name))
            .filter((n): n is string => !!n),
          created_at: issue.created_at,
          updated_at: issue.updated_at,
        });
        if (issues.length >= maxResults) break;
      }

      if (data.length < 100) break;
      page++;
    }

    return { content: [{ type: "text" as const, text: JSON.stringify(issues, null, 2) }] };
  },
  { annotations: { readOnly: true } }
);

const getIssueTool = tool(
  "github_get_issue",
  "Get detailed information about a specific issue including comments",
  {
    owner: z.string().describe("Repository owner"),
    repo: z.string().describe("Repository name"),
    issue_number: z.number().describe("The issue number"),
  },
  async ({ owner, repo, issue_number }) => {
    const octokit = getOctokit();
    const { data: issue } = await octokit.rest.issues.get({
      owner,
      repo,
      issue_number,
    });
    const { data: commentsData } = await octokit.rest.issues.listComments({
      owner,
      repo,
      issue_number,
      per_page: 20,
    });

    const result = {
      number: issue.number,
      title: issue.title,
      body: issue.body ?? null,
      state: issue.state,
      assignees: issue.assignees?.map((a) => a.login) || [],
      labels: issue.labels
        .map((l) => (typeof l === "string" ? l : l.name))
        .filter((n): n is string => !!n),
      comments: commentsData.map((c) => ({
        author: c.user?.login || "unknown",
        body: c.body || "",
        created_at: c.created_at,
      })),
    };

    return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
  },
  { annotations: { readOnly: true } }
);

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
            title: (commit.commit.message || "").split("\n")[0],
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

const listProjectItemsTool = tool(
  "github_list_project_items",
  "List items from a GitHub Project v2 with all field values (status, priority, size, sprint, etc.)",
  {
    owner: z.string().describe("Organization that owns the project"),
    project_number: z.number().describe("The project number"),
  },
  async ({ owner, project_number }) => {
    const items = await fetchProjectItems(owner, project_number);
    return { content: [{ type: "text" as const, text: JSON.stringify(items, null, 2) }] };
  },
  { annotations: { readOnly: true } }
);

const getReadmeTool = tool(
  "github_get_readme",
  "Get the README content of a repository",
  {
    owner: z.string().describe("Repository owner"),
    repo: z.string().describe("Repository name"),
  },
  async ({ owner, repo }) => {
    const octokit = getOctokit();
    const filenames = ["README.md", "readme.md", "README.txt", "README"];

    for (const filename of filenames) {
      try {
        const { data } = await octokit.rest.repos.getContent({
          owner,
          repo,
          path: filename,
        });
        if ("content" in data && data.content) {
          const content = Buffer.from(data.content, "base64").toString("utf-8");
          return { content: [{ type: "text" as const, text: content }] };
        }
      } catch {
        continue;
      }
    }

    return { content: [{ type: "text" as const, text: "No README found" }] };
  },
  { annotations: { readOnly: true } }
);

const getFileTool = tool(
  "github_get_file",
  "Get the content of a specific file from a repository",
  {
    owner: z.string().describe("Repository owner"),
    repo: z.string().describe("Repository name"),
    path: z.string().describe("Path to the file within the repository"),
    ref: z
      .string()
      .optional()
      .describe("Git ref (branch, tag, or commit SHA)"),
  },
  async ({ owner, repo, path, ref }) => {
    const octokit = getOctokit();
    try {
      const { data } = await octokit.rest.repos.getContent({
        owner,
        repo,
        path,
        ref,
      });
      if ("content" in data && data.content) {
        const content = Buffer.from(data.content, "base64").toString("utf-8");
        return { content: [{ type: "text" as const, text: content }] };
      }
      return { content: [{ type: "text" as const, text: "File has no content" }] };
    } catch (error) {
      return {
        content: [
          {
            type: "text" as const,
            text: `Error: ${error instanceof Error ? error.message : String(error)}`,
          },
        ],
        isError: true,
      };
    }
  },
  { annotations: { readOnly: true } }
);

const listDirectoryTool = tool(
  "github_list_directory",
  "List contents of a directory in a repository",
  {
    owner: z.string().describe("Repository owner"),
    repo: z.string().describe("Repository name"),
    path: z
      .string()
      .optional()
      .describe("Path to directory (empty for root)"),
    ref: z.string().optional().describe("Git ref"),
  },
  async ({ owner, repo, path, ref }) => {
    const octokit = getOctokit();
    try {
      const { data } = await octokit.rest.repos.getContent({
        owner,
        repo,
        path: path || "",
        ref,
      });

      if (Array.isArray(data)) {
        const items = data.map((item) => ({
          name: item.name,
          type: item.type,
          path: item.path,
          size: item.size,
        }));
        return { content: [{ type: "text" as const, text: JSON.stringify(items, null, 2) }] };
      }
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify(
              { name: data.name, type: data.type, path: data.path, size: data.size },
              null,
              2
            ),
          },
        ],
      };
    } catch (error) {
      return {
        content: [
          {
            type: "text" as const,
            text: `Error: ${error instanceof Error ? error.message : String(error)}`,
          },
        ],
        isError: true,
      };
    }
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

const listPullsTool = tool(
  "github_list_pulls",
  "List pull requests for a repository with optional filters",
  {
    owner: z.string().describe("Repository owner"),
    repo: z.string().describe("Repository name"),
    state: z.enum(["open", "closed", "all"]).optional().describe("Filter by state (default: open)"),
    sort: z.enum(["created", "updated", "popularity"]).optional().describe("Sort field (default: created)"),
    limit: z.number().optional().describe("Maximum PRs to return (default: 30)"),
  },
  async ({ owner, repo, state, sort, limit }) => {
    const octokit = getOctokit();
    const maxResults = limit ?? 30;
    const pulls: Array<{
      number: number;
      title: string;
      state: string;
      author: string;
      draft: boolean;
      labels: string[];
      created_at: string;
      updated_at: string;
      url: string;
    }> = [];
    let page = 1;

    while (pulls.length < maxResults) {
      const { data } = await octokit.rest.pulls.list({
        owner,
        repo,
        state: state ?? "open",
        sort: sort ?? "created",
        direction: "desc",
        per_page: Math.min(100, maxResults - pulls.length),
        page,
      });

      for (const pr of data) {
        pulls.push({
          number: pr.number,
          title: pr.title,
          state: pr.state,
          author: pr.user?.login || "unknown",
          draft: pr.draft || false,
          labels: pr.labels.map((l) => l.name).filter((n): n is string => !!n),
          created_at: pr.created_at,
          updated_at: pr.updated_at,
          url: pr.html_url,
        });
        if (pulls.length >= maxResults) break;
      }

      if (data.length < 100) break;
      page++;
    }

    return { content: [{ type: "text" as const, text: JSON.stringify(pulls, null, 2) }] };
  },
  { annotations: { readOnly: true } }
);

const getPullTool = tool(
  "github_get_pull",
  "Get detailed information about a specific pull request including diff stats, changed files, and review comments",
  {
    owner: z.string().describe("Repository owner"),
    repo: z.string().describe("Repository name"),
    pull_number: z.number().describe("The pull request number"),
  },
  async ({ owner, repo, pull_number }) => {
    const octokit = getOctokit();

    const [{ data: pr }, { data: files }, { data: reviews }, { data: comments }] = await Promise.all([
      octokit.rest.pulls.get({ owner, repo, pull_number }),
      octokit.rest.pulls.listFiles({ owner, repo, pull_number, per_page: 50 }),
      octokit.rest.pulls.listReviews({ owner, repo, pull_number, per_page: 20 }),
      octokit.rest.pulls.listReviewComments({ owner, repo, pull_number, per_page: 30 }),
    ]);

    const result = {
      number: pr.number,
      title: pr.title,
      body: pr.body ?? null,
      state: pr.state,
      merged: pr.merged,
      draft: pr.draft,
      author: pr.user?.login || "unknown",
      base: pr.base.ref,
      head: pr.head.ref,
      labels: pr.labels.map((l) => l.name).filter((n): n is string => !!n),
      created_at: pr.created_at,
      updated_at: pr.updated_at,
      merged_at: pr.merged_at,
      url: pr.html_url,
      diff_stats: {
        additions: pr.additions,
        deletions: pr.deletions,
        changed_files: pr.changed_files,
      },
      files: files.map((f) => ({
        filename: f.filename,
        status: f.status,
        additions: f.additions,
        deletions: f.deletions,
      })),
      reviews: reviews.map((r) => ({
        author: r.user?.login || "unknown",
        state: r.state,
        body: r.body || null,
        submitted_at: r.submitted_at,
      })),
      review_comments: comments.map((c) => ({
        author: c.user?.login || "unknown",
        body: c.body,
        path: c.path,
        line: c.line ?? c.original_line ?? null,
        created_at: c.created_at,
      })),
    };

    return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
  },
  { annotations: { readOnly: true } }
);

// --- Write Tools ---

const createIssueTool = tool(
  "github_create_issue",
  "Create a new GitHub issue. Requires user approval before execution.",
  {
    owner: z.string().describe("Repository owner"),
    repo: z.string().describe("Repository name"),
    title: z.string().describe("Issue title"),
    body: z.string().optional().describe("Issue body (markdown)"),
    labels: z.array(z.string()).optional().describe("Labels to apply"),
    assignees: z.array(z.string()).optional().describe("Usernames to assign"),
  },
  async ({ owner, repo, title, body, labels, assignees }) => {
    const octokit = getOctokit();
    const { data } = await octokit.rest.issues.create({
      owner,
      repo,
      title,
      body,
      labels,
      assignees,
    });
    return {
      content: [
        {
          type: "text" as const,
          text: JSON.stringify(
            {
              number: data.number,
              url: data.html_url,
              title: data.title,
              state: data.state,
            },
            null,
            2
          ),
        },
      ],
    };
  },
  { annotations: { readOnly: false, destructive: false } }
);

const updateIssueTool = tool(
  "github_update_issue",
  "Update an existing GitHub issue. Requires user approval before execution.",
  {
    owner: z.string().describe("Repository owner"),
    repo: z.string().describe("Repository name"),
    issue_number: z.number().describe("Issue number to update"),
    title: z.string().optional().describe("New title"),
    body: z.string().optional().describe("New body"),
    state: z.enum(["open", "closed"]).optional().describe("New state"),
    labels: z.array(z.string()).optional().describe("Labels to set"),
    assignees: z.array(z.string()).optional().describe("Assignees to set"),
  },
  async ({ owner, repo, issue_number, title, body, state, labels, assignees }) => {
    const octokit = getOctokit();
    const { data } = await octokit.rest.issues.update({
      owner,
      repo,
      issue_number,
      title,
      body,
      state,
      labels,
      assignees,
    });
    return {
      content: [
        {
          type: "text" as const,
          text: JSON.stringify(
            {
              number: data.number,
              url: data.html_url,
              title: data.title,
              state: data.state,
            },
            null,
            2
          ),
        },
      ],
    };
  },
  { annotations: { readOnly: false, destructive: false } }
);

const addCommentTool = tool(
  "github_add_comment",
  "Add a comment to a GitHub issue. Requires user approval before execution.",
  {
    owner: z.string().describe("Repository owner"),
    repo: z.string().describe("Repository name"),
    issue_number: z.number().describe("Issue number to comment on"),
    body: z.string().describe("Comment body (markdown)"),
  },
  async ({ owner, repo, issue_number, body }) => {
    const octokit = getOctokit();
    const { data } = await octokit.rest.issues.createComment({
      owner,
      repo,
      issue_number,
      body,
    });
    return {
      content: [
        {
          type: "text" as const,
          text: JSON.stringify(
            { id: data.id, url: data.html_url, created_at: data.created_at },
            null,
            2
          ),
        },
      ],
    };
  },
  { annotations: { readOnly: false, destructive: false } }
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

Common commands:
- pr list --repo owner/repo
- pr create --repo owner/repo --title "Title" --body "Body" --base main --head branch-name
- pr view 123 --repo owner/repo
- pr merge 123 --repo owner/repo --squash
- workflow list --repo owner/repo
- workflow run ci.yml --repo owner/repo
- api repos/owner/repo/contents/path (raw GitHub API calls)
- repo clone owner/repo /tmp/repo (clone for multi-file operations)

For multi-file code changes: clone the repo, make changes with git, push, then create a PR.`,
  {
    command: z.string().describe("The gh command to execute (without the 'gh' prefix). Example: 'pr list --repo owner/repo'"),
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

const READ_TOOLS = [
  listReposTool,
  getRepoTool,
  listIssuesTool,
  getIssueTool,
  listProjectItemsTool,
  listProjectFieldsTool,
  listPullsTool,
  getPullTool,
  getReadmeTool,
  getFileTool,
  listDirectoryTool,
];

const WRITE_TOOLS = [createIssueTool, updateIssueTool, addCommentTool, githubCliTool];

export const WRITE_TOOL_NAMES = WRITE_TOOLS.map((t) => t.name);

export function createGitHubMcpServer(): McpSdkServerConfigWithInstance {
  return createSdkMcpServer({
    name: "github",
    version: "0.1.0",
    tools: [...READ_TOOLS, ...WRITE_TOOLS],
  });
}
