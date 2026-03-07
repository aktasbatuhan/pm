import { Octokit } from "@octokit/rest";
import { writeFileSync, existsSync, readFileSync } from "fs";
import { join } from "path";
import { generateFullKnowledge } from "../knowledge/generator.ts";

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
  try {
    const res = await fetch("https://api.github.com/graphql", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        query: `query($org: String!, $num: Int!) {
          organization(login: $org) {
            projectV2(number: $num) {
              items(first: 100) {
                nodes {
                  content {
                    ... on Issue { repository { name } }
                    ... on PullRequest { repository { name } }
                  }
                }
              }
            }
          }
        }`,
        variables: { org, num: projectNumber },
      }),
    });
    const json = (await res.json()) as {
      data?: {
        organization: {
          projectV2: {
            items: {
              nodes: Array<{ content: { repository?: { name: string } } | null }>;
            };
          };
        };
      };
    };
    const names = new Set<string>();
    for (const item of json.data?.organization?.projectV2?.items?.nodes || []) {
      const name = item.content?.repository?.name;
      if (name) names.add(name);
    }
    return [...names];
  } catch {
    return [];
  }
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

export function saveGitHubConfig(opts: {
  token: string;
  org: string;
  projectNumber: number;
}): { created: boolean } {
  const env = loadEnv();
  const existed = existsSync(ENV_PATH);

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
