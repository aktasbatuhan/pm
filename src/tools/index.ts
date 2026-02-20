export { createGitHubMcpServer, WRITE_TOOL_NAMES as GITHUB_WRITE_TOOL_NAMES } from "./github.ts";
export { createKnowledgeMcpServer, KNOWLEDGE_WRITE_TOOL_NAMES } from "./knowledge.ts";
export { createSchedulerMcpServer, SCHEDULER_WRITE_TOOL_NAMES } from "./scheduler.ts";
export { createSlackMcpServer, SLACK_WRITE_TOOL_NAMES } from "./slack.ts";
export { createVisualizationMcpServer } from "./visualization.ts";
export { createPostHogMcpServer, POSTHOG_WRITE_TOOL_NAMES } from "./posthog.ts";
export { createDashboardMcpServer, DASHBOARD_TOOL_NAMES } from "./dashboard.ts";

import { WRITE_TOOL_NAMES as _GH_WRITE } from "./github.ts";
import { KNOWLEDGE_WRITE_TOOL_NAMES as _K_WRITE } from "./knowledge.ts";
import { SCHEDULER_WRITE_TOOL_NAMES as _S_WRITE } from "./scheduler.ts";
import { SLACK_WRITE_TOOL_NAMES as _SL_WRITE } from "./slack.ts";
import { POSTHOG_WRITE_TOOL_NAMES as _PH_WRITE } from "./posthog.ts";
import { DASHBOARD_TOOL_NAMES as _D_WRITE } from "./dashboard.ts";

export const WRITE_TOOL_NAMES = [..._GH_WRITE, ..._K_WRITE, ..._S_WRITE, ..._SL_WRITE, ..._PH_WRITE, ..._D_WRITE];
