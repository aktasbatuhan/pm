import { Octokit } from "@octokit/rest";
import { writeFileSync, existsSync, readFileSync, readdirSync, unlinkSync, rmSync } from "fs";
import { join } from "path";
import { generateFullKnowledge } from "../knowledge/generator.ts";
import { KNOWLEDGE_DIR, MEMORY_DIR } from "../paths.ts";

const ENV_PATH = join(import.meta.dir, "../../.env");

export interface ProjectNode {
  number: number;
  title: string;
}

export interface SetupStatus {
  configured: boolean;
  hasToken: boolean;
  org: string;
  projectNumber: number;
}

export function getSetupStatus(): SetupStatus {
  return {
    configured: !!(process.env.GITHUB_ORG && process.env.GITHUB_PROJECT_NUMBER),
    hasToken: !!process.env.GITHUB_TOKEN,
    org: process.env.GITHUB_ORG || "",
    projectNumber: parseInt(process.env.GITHUB_PROJECT_NUMBER || "0", 10),
  };
}

export async function validateToken(token: string): Promise<{ valid: boolean; username: string }> {
  const octokit = new Octokit({ auth: token });
  try {
    const { data } = await octokit.rest.users.getAuthenticated();
    return { valid: true, username: data.login };
  } catch {
    return { valid: false, username: "" };
  }
}

export async function listOrgs(token: string): Promise<string[]> {
  const octokit = new Octokit({ auth: token });
  try {
    const { data } = await octokit.rest.orgs.listForAuthenticatedUser();
    return data.map((o) => o.login);
  } catch {
    return [];
  }
}

export async function listProjects(token: string, org: string): Promise<ProjectNode[]> {
  const headers = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };

  // Try org first
  try {
    const res = await fetch("https://api.github.com/graphql", {
      method: "POST",
      headers,
      body: JSON.stringify({
        query: `query($org: String!) {
          organization(login: $org) {
            projectsV2(first: 20) {
              nodes { number title }
            }
          }
        }`,
        variables: { org },
      }),
    });
    const json = (await res.json()) as {
      data?: { organization: { projectsV2: { nodes: ProjectNode[] } } };
    };
    const projects = json.data?.organization?.projectsV2?.nodes;
    if (projects && projects.length > 0) return projects;
  } catch {
    // fall through
  }

  // Try user
  try {
    const res = await fetch("https://api.github.com/graphql", {
      method: "POST",
      headers,
      body: JSON.stringify({
        query: `query($login: String!) {
          user(login: $login) {
            projectsV2(first: 20) {
              nodes { number title }
            }
          }
        }`,
        variables: { login: org },
      }),
    });
    const json = (await res.json()) as {
      data?: { user: { projectsV2: { nodes: ProjectNode[] } } };
    };
    return json.data?.user?.projectsV2?.nodes || [];
  } catch {
    return [];
  }
}

export async function discoverReposFromProject(
  token: string,
  org: string,
  projectNumber: number
): Promise<string[]> {
  // Try organization first, then user — GitHub projects can live under either
  for (const ownerType of ["organization", "user"] as const) {
    try {
      const res = await fetch("https://api.github.com/graphql", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query: `query($login: String!, $num: Int!) {
            ${ownerType}(login: $login) {
              projectV2(number: $num) {
                items(first: 100) {
                  nodes {
                    content {
                      ... on Issue { repository { name } }
                      ... on PullRequest { repository { name } }
                    }
                  }
                }
                repositories(first: 50) {
                  nodes { name }
                }
              }
            }
          }`,
          variables: { login: org, num: projectNumber },
        }),
      });
      const json = await res.json() as any;
      const project = json.data?.[ownerType]?.projectV2;
      if (!project) continue; // wrong owner type, try next

      const names = new Set<string>();

      // Get repos from project items (issues/PRs)
      for (const item of project.items?.nodes || []) {
        const name = item?.content?.repository?.name;
        if (name) names.add(name);
      }

      // Also get repos linked directly to the project
      for (const repo of project.repositories?.nodes || []) {
        if (repo?.name) names.add(repo.name);
      }

      return [...names];
    } catch {
      continue;
    }
  }

  // Fallback: list org/user repos if project query fails
  try {
    const res = await fetch(`https://api.github.com/orgs/${org}/repos?per_page=50&sort=updated`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) {
      const repos = await res.json() as Array<{ name: string }>;
      return repos.map(r => r.name);
    }
    // Try as user
    const userRes = await fetch(`https://api.github.com/users/${org}/repos?per_page=50&sort=updated`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (userRes.ok) {
      const repos = await userRes.json() as Array<{ name: string }>;
      return repos.map(r => r.name);
    }
  } catch {}

  return [];
}

export async function generateKnowledge(
  org: string,
  repoNames: string[],
  onProgress?: (msg: string) => void | Promise<void>,
  token?: string
): Promise<void> {
  // The generator reads process.env.GITHUB_TOKEN — ensure it's set
  if (token && !process.env.GITHUB_TOKEN) {
    process.env.GITHUB_TOKEN = token;
  }

  await generateFullKnowledge(org, repoNames, onProgress);
}

function loadEnv(): Record<string, string> {
  if (!existsSync(ENV_PATH)) return {};
  const content = readFileSync(ENV_PATH, "utf-8");
  const env: Record<string, string> = {};
  for (const line of content.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eqIdx = trimmed.indexOf("=");
    if (eqIdx === -1) continue;
    env[trimmed.slice(0, eqIdx)] = trimmed.slice(eqIdx + 1);
  }
  return env;
}

function saveEnvFile(env: Record<string, string>) {
  const lines = Object.entries(env).map(([k, v]) => `${k}=${v}`);
  writeFileSync(ENV_PATH, lines.join("\n") + "\n");
}

/**
 * Clear generated knowledge and memory when switching to a different org/project.
 * Prevents stale data from a previous project from leaking into the new one.
 */
function clearProjectData(newOrg: string, newProjectNumber: number) {
  const currentOrg = process.env.GITHUB_ORG;
  const currentProject = parseInt(process.env.GITHUB_PROJECT_NUMBER || "0", 10);

  // Only clear if actually switching to a different project
  if (currentOrg === newOrg && currentProject === newProjectNumber) return;
  if (!currentOrg) return; // first setup, nothing to clear

  console.log(`[setup] Project changed from ${currentOrg}/#${currentProject} to ${newOrg}/#${newProjectNumber} — clearing old data`);

  // Clear knowledge files (overview + repo docs)
  try {
    const overviewPath = join(KNOWLEDGE_DIR, "overview.md");
    if (existsSync(overviewPath)) unlinkSync(overviewPath);

    const companyPath = join(KNOWLEDGE_DIR, "company.md");
    if (existsSync(companyPath)) unlinkSync(companyPath);

    const reposDir = join(KNOWLEDGE_DIR, "repos");
    if (existsSync(reposDir)) {
      for (const f of readdirSync(reposDir)) {
        if (f.endsWith(".md")) unlinkSync(join(reposDir, f));
      }
    }

    const reportsDir = join(KNOWLEDGE_DIR, "sprint-reports");
    if (existsSync(reportsDir)) rmSync(reportsDir, { recursive: true, force: true });
  } catch (err) {
    console.warn("[setup] Failed to clear knowledge:", err);
  }

  // Clear memory files (they contain project-specific context)
  try {
    if (existsSync(MEMORY_DIR)) {
      rmSync(MEMORY_DIR, { recursive: true, force: true });
    }
  } catch (err) {
    console.warn("[setup] Failed to clear memory:", err);
  }
}

export function saveGitHubConfig(opts: {
  token: string;
  org: string;
  projectNumber: number;
}): { created: boolean } {
  const env = loadEnv();
  const existed = existsSync(ENV_PATH);

  clearProjectData(opts.org, opts.projectNumber);

  env.GITHUB_TOKEN = opts.token;
  env.GITHUB_ORG = opts.org;
  env.GITHUB_PROJECT_NUMBER = String(opts.projectNumber);
  if (!env.PORT) env.PORT = "3000";

  saveEnvFile(env);

  process.env.GITHUB_TOKEN = opts.token;
  process.env.GITHUB_ORG = opts.org;
  process.env.GITHUB_PROJECT_NUMBER = String(opts.projectNumber);

  return { created: !existed };
}

export function completeSetup(opts: {
  token: string;
  org: string;
  projectNumber: number;
  anthropicKey?: string;
  openrouterKey?: string;
}): { created: boolean } {
  const env = loadEnv();
  const existed = existsSync(ENV_PATH);

  env.GITHUB_TOKEN = opts.token;
  env.GITHUB_ORG = opts.org;
  env.GITHUB_PROJECT_NUMBER = String(opts.projectNumber);
  if (opts.anthropicKey) env.ANTHROPIC_API_KEY = opts.anthropicKey;
  if (opts.openrouterKey) env.OPENROUTER_API_KEY = opts.openrouterKey;
  if (!env.PORT) env.PORT = "3000";

  saveEnvFile(env);

  // Update process.env so the app works without restart
  process.env.GITHUB_TOKEN = opts.token;
  process.env.GITHUB_ORG = opts.org;
  process.env.GITHUB_PROJECT_NUMBER = String(opts.projectNumber);

  return { created: !existed };
}
