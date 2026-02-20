// PM Agent — Frontend

// --- Mermaid Initialization ---
mermaid.initialize({
  startOnLoad: false,
  theme: "dark",
  themeVariables: {
    primaryColor: "#e8912d",
    primaryTextColor: "#e6edf3",
    primaryBorderColor: "#1e2328",
    lineColor: "#484f58",
    secondaryColor: "#111519",
    tertiaryColor: "#0a0e13",
    background: "#111519",
    mainBkg: "#111519",
    nodeBorder: "#1e2328",
    fontFamily: "SF Mono, Fira Code, JetBrains Mono, Consolas, monospace",
    fontSize: "12px",
  },
});

// --- Chart.js Dark Theme Defaults ---
const CHART_COLORS = ["#e8912d", "#00c853", "#ff3d3d", "#58a6ff", "#d29922", "#b36d1a", "#8b949e"];

function getChartThemeDefaults() {
  return {
    color: "#8b949e",
    borderColor: "#1e2328",
    plugins: {
      legend: {
        labels: { color: "#8b949e", font: { family: "SF Mono, Fira Code, monospace", size: 10 } },
      },
      title: { color: "#e6edf3", font: { family: "SF Mono, Fira Code, monospace", size: 11 } },
    },
    scales: {
      x: {
        ticks: { color: "#484f58", font: { family: "SF Mono, Fira Code, monospace", size: 10 } },
        grid: { color: "#1e2328" },
        border: { color: "#1e2328" },
      },
      y: {
        ticks: { color: "#484f58", font: { family: "SF Mono, Fira Code, monospace", size: 10 } },
        grid: { color: "#1e2328" },
        border: { color: "#1e2328" },
      },
    },
  };
}

// --- Visualization Renderers ---

function renderChartElement(container, input) {
  const wrapper = document.createElement("div");
  wrapper.className = "chart-container";
  wrapper.style.height = "300px";
  wrapper.style.margin = "10px 0";

  if (input.title) {
    const title = document.createElement("div");
    title.className = "chart-title";
    title.textContent = input.title;
    wrapper.appendChild(title);
  }

  const canvas = document.createElement("canvas");
  canvas.style.width = "100%";
  canvas.style.height = "280px";
  canvas.style.display = "block";
  wrapper.appendChild(canvas);
  container.appendChild(wrapper);

  // Apply default colors if not provided
  const datasets = input.data.datasets.map((ds, i) => {
    const copy = { ...ds };
    if (!copy.backgroundColor) {
      if (["pie", "doughnut", "polarArea"].includes(input.type)) {
        copy.backgroundColor = input.data.labels.map((_, j) => CHART_COLORS[j % CHART_COLORS.length]);
      } else {
        copy.backgroundColor = CHART_COLORS[i % CHART_COLORS.length];
      }
    }
    if (input.type === "line" && !copy.borderColor) {
      copy.borderColor = CHART_COLORS[i % CHART_COLORS.length];
      copy.backgroundColor = copy.backgroundColor || "transparent";
    }
    return copy;
  });

  const themeDefaults = getChartThemeDefaults();
  const noAxes = ["pie", "doughnut", "polarArea", "radar"].includes(input.type);

  const inputOpts = input.options || {};
  const { scales: inputScales, plugins: inputPlugins, ...restOpts } = inputOpts;
  const mergedScales = noAxes ? {} : {
    scales: {
      x: { ...themeDefaults.scales.x, ...(inputScales?.x || {}) },
      y: { ...themeDefaults.scales.y, ...(inputScales?.y || {}) },
    },
  };

  const config = {
    type: input.type,
    data: { labels: input.data.labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      color: themeDefaults.color,
      borderColor: themeDefaults.borderColor,
      plugins: { ...themeDefaults.plugins, ...(inputPlugins || {}) },
      ...mergedScales,
      ...restOpts,
    },
  };

  try {
    new Chart(canvas, config);
  } catch (error) {
    console.error("[viz] Chart.js error:", error);
    canvas.style.display = "none";
    const errorDiv = document.createElement("div");
    errorDiv.style.color = "var(--red)";
    errorDiv.style.padding = "10px";
    errorDiv.textContent = "Chart render error: " + error.message;
    wrapper.appendChild(errorDiv);
  }
}

function renderMermaidElement(container, input) {
  const wrapper = document.createElement("div");
  wrapper.className = "mermaid-container";

  if (input.title) {
    const title = document.createElement("div");
    title.className = "diagram-title";
    title.textContent = input.title;
    wrapper.appendChild(title);
  }

  const mermaidDiv = document.createElement("div");
  mermaidDiv.className = "mermaid";
  mermaidDiv.textContent = input.code;
  wrapper.appendChild(mermaidDiv);
  container.appendChild(wrapper);

  // Render asynchronously
  mermaid.run({ nodes: [mermaidDiv] }).catch((err) => {
    mermaidDiv.textContent = "Diagram render error: " + err.message;
    mermaidDiv.style.color = "var(--red)";
  });
}

// --- Setup Wizard ---

const setupOverlay = document.getElementById("setup-overlay");
const setupState = {
  token: "", username: "", org: "", selectedProject: null,
  knowledgeFileCount: 0, integrationsConfigured: 0,
};

function showSetup() {
  setupOverlay.classList.remove("hidden");
}

function hideSetup() {
  setupOverlay.classList.add("hidden");
}

function goToSetupStep(step) {
  document.querySelectorAll(".setup-step").forEach((el) => el.classList.add("hidden"));
  document.getElementById(`setup-step-${step}`).classList.remove("hidden");
  document.querySelectorAll(".step-dot").forEach((dot) => {
    const s = parseInt(dot.dataset.step);
    dot.classList.remove("active", "done");
    if (s < step) dot.classList.add("done");
    if (s === step) dot.classList.add("active");
  });
}

function setSetupLoading(show, text) {
  const el = document.getElementById("setup-loading");
  document.getElementById("setup-loading-text").textContent = text || "Working...";
  el.classList.toggle("hidden", !show);
}

// Step 1: Validate token
document.getElementById("btn-validate-token").addEventListener("click", async () => {
  const token = document.getElementById("setup-token").value.trim();
  const status = document.getElementById("token-status");
  if (!token) {
    status.textContent = "Enter a token";
    status.className = "step-status error";
    return;
  }

  setSetupLoading(true, "Validating token...");
  try {
    const res = await fetch("/api/setup/validate-token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    const data = await res.json();
    setSetupLoading(false);

    if (data.valid) {
      setupState.token = token;
      setupState.username = data.username;
      status.textContent = `Authenticated as ${data.username}`;
      status.className = "step-status success";

      // Populate org options
      const orgEl = document.getElementById("org-options");
      const orgs = data.orgs || [];
      orgEl.innerHTML = [data.username, ...orgs]
        .map((o) => `<span class="org-option" data-org="${escapeHtml(o)}">${escapeHtml(o)}</span>`)
        .join("");

      orgEl.querySelectorAll(".org-option").forEach((el) => {
        el.addEventListener("click", () => {
          orgEl.querySelectorAll(".org-option").forEach((o) => o.classList.remove("selected"));
          el.classList.add("selected");
          document.getElementById("setup-org").value = el.dataset.org;
        });
      });

      document.getElementById("setup-org").value = orgs[0] || data.username;
      if (orgs[0]) {
        orgEl.querySelector(`[data-org="${orgs[0]}"]`)?.classList.add("selected");
      }

      goToSetupStep(2);
    } else {
      status.textContent = "Invalid token";
      status.className = "step-status error";
    }
  } catch (err) {
    setSetupLoading(false);
    status.textContent = `Error: ${err.message}`;
    status.className = "step-status error";
  }
});

// Enter key on token input
document.getElementById("setup-token").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("btn-validate-token").click();
});

// Step 2: Fetch projects
document.getElementById("btn-fetch-projects").addEventListener("click", async () => {
  const org = document.getElementById("setup-org").value.trim();
  if (!org) return;
  setupState.org = org;

  setSetupLoading(true, "Fetching projects...");
  try {
    const res = await fetch("/api/setup/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: setupState.token, org }),
    });
    const data = await res.json();
    setSetupLoading(false);

    const listEl = document.getElementById("projects-list");
    if (!data.projects || data.projects.length === 0) {
      listEl.innerHTML = '<div style="color: var(--text-muted); padding: 12px; font-size: 13px;">No projects found.</div>';
      goToSetupStep(3);
      return;
    }

    listEl.innerHTML = data.projects
      .map(
        (p) => `<div class="project-option" data-number="${p.number}">
          <div class="project-title">#${p.number} — ${escapeHtml(p.title)}</div>
        </div>`
      )
      .join("");

    listEl.querySelectorAll(".project-option").forEach((el) => {
      el.addEventListener("click", () => {
        listEl.querySelectorAll(".project-option").forEach((o) => o.classList.remove("selected"));
        el.classList.add("selected");
        setupState.selectedProject = parseInt(el.dataset.number);
      });
    });

    goToSetupStep(3);
  } catch (err) {
    setSetupLoading(false);
    alert(`Error: ${err.message}`);
  }
});

// Enter key on org input
document.getElementById("setup-org").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("btn-fetch-projects").click();
});

// Step 3: Connect project (save config, then advance to knowledge generation)
document.getElementById("btn-connect-project").addEventListener("click", async () => {
  if (!setupState.selectedProject) {
    alert("Select a project first");
    return;
  }

  setSetupLoading(true, "Saving configuration...");
  try {
    const res = await fetch("/api/setup/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token: setupState.token,
        org: setupState.org,
        projectNumber: setupState.selectedProject,
      }),
    });
    const data = await res.json();
    setSetupLoading(false);

    if (data.success) {
      goToSetupStep(4);
      discoverRepos();
    } else {
      alert("Failed to save configuration");
    }
  } catch (err) {
    setSetupLoading(false);
    alert(`Setup failed: ${err.message}`);
  }
});

// Step 4 Phase 1: Discover repos and show selection
let discoveredRepos = [];

async function discoverRepos() {
  const loadingEl = document.getElementById("repo-selection-loading");
  const listEl = document.getElementById("repo-selection-list");
  const actionsEl = document.getElementById("repo-selection-actions");

  // Show selection phase, hide generation phase
  document.getElementById("repo-selection-phase").style.display = "";
  document.getElementById("knowledge-gen-phase").style.display = "none";
  loadingEl.textContent = "Discovering repositories...";
  loadingEl.className = "step-status";
  listEl.innerHTML = "";
  actionsEl.style.display = "none";

  try {
    const res = await fetch("/api/setup/discover-repos", { method: "POST" });
    const data = await res.json();
    discoveredRepos = data.repos || [];

    if (discoveredRepos.length === 0) {
      loadingEl.textContent = "No repositories found in this project.";
      loadingEl.className = "step-status error";
      actionsEl.style.display = "";
      return;
    }

    loadingEl.textContent = `Found ${discoveredRepos.length} repositories`;
    loadingEl.className = "step-status success";

    listEl.innerHTML = discoveredRepos.map((repo) => `
      <label class="repo-selection-item selected" data-repo="${escapeHtml(repo)}">
        <input type="checkbox" checked />
        <span class="repo-name">${escapeHtml(repo)}</span>
      </label>
    `).join("");

    // Toggle selected class on click
    listEl.querySelectorAll(".repo-selection-item").forEach((el) => {
      const cb = el.querySelector("input[type='checkbox']");
      cb.addEventListener("change", () => {
        el.classList.toggle("selected", cb.checked);
      });
    });

    actionsEl.style.display = "";
  } catch (err) {
    loadingEl.textContent = `Error: ${err.message}`;
    loadingEl.className = "step-status error";
  }
}

// Select all / none controls
document.getElementById("btn-repos-all").addEventListener("click", () => {
  document.querySelectorAll("#repo-selection-list .repo-selection-item").forEach((el) => {
    el.querySelector("input[type='checkbox']").checked = true;
    el.classList.add("selected");
  });
});

document.getElementById("btn-repos-none").addEventListener("click", () => {
  document.querySelectorAll("#repo-selection-list .repo-selection-item").forEach((el) => {
    el.querySelector("input[type='checkbox']").checked = false;
    el.classList.remove("selected");
  });
});

// Generate knowledge for selected repos
document.getElementById("btn-generate-knowledge").addEventListener("click", () => {
  const selected = [];
  document.querySelectorAll("#repo-selection-list .repo-selection-item").forEach((el) => {
    if (el.querySelector("input[type='checkbox']").checked) {
      selected.push(el.dataset.repo);
    }
  });

  if (selected.length === 0) {
    // Skip generation entirely, go to integrations
    goToSetupStep(6);
    return;
  }

  // Switch to generation phase
  document.getElementById("repo-selection-phase").style.display = "none";
  document.getElementById("knowledge-gen-phase").style.display = "";
  startKnowledgeGeneration(selected);
});

// Step 4 Phase 2: SSE knowledge generation with real-time progress
function startKnowledgeGeneration(repos) {
  const logEl = document.getElementById("knowledge-progress");
  const statusEl = document.getElementById("knowledge-progress-status");
  logEl.innerHTML = "";
  statusEl.textContent = "";

  const reposParam = encodeURIComponent(repos.join(","));
  const evtSource = new EventSource(`/api/setup/generate-knowledge?repos=${reposParam}`);

  evtSource.addEventListener("progress", (e) => {
    const data = JSON.parse(e.data);
    const line = document.createElement("div");
    line.className = `progress-line phase-${data.phase}`;

    const icon = (data.phase === "complete" || data.phase === "writing") ? "done" :
                 data.phase === "warning" ? "warning" : "active";
    line.innerHTML = `<span class="progress-icon progress-icon-${icon}"></span>${escapeHtml(data.message)}`;

    logEl.appendChild(line);
    logEl.scrollTop = logEl.scrollHeight;
  });

  evtSource.addEventListener("complete", () => {
    evtSource.close();
    const line = document.createElement("div");
    line.className = "progress-line phase-complete";
    line.innerHTML = '<span class="progress-icon progress-icon-done"></span>Knowledge generation complete';
    logEl.appendChild(line);
    logEl.scrollTop = logEl.scrollHeight;

    statusEl.textContent = "Complete! Loading files for review...";
    statusEl.className = "step-status success";

    setTimeout(() => loadKnowledgeForReview(), 1000);
  });

  evtSource.addEventListener("gen_error", (e) => {
    evtSource.close();
    const data = JSON.parse(e.data);
    statusEl.textContent = `Error: ${data.message}`;
    statusEl.className = "step-status error";
    appendRetrySkipButtons(statusEl.parentElement, repos);
  });

  evtSource.onerror = () => {
    if (evtSource.readyState === EventSource.CLOSED) return;
    setTimeout(() => {
      if (evtSource.readyState !== EventSource.CLOSED) {
        evtSource.close();
        statusEl.textContent = "Connection lost during generation.";
        statusEl.className = "step-status error";
        appendRetrySkipButtons(statusEl.parentElement, repos);
      }
    }, 5000);
  };
}

function appendRetrySkipButtons(container, repos) {
  container.querySelectorAll(".setup-retry-btn, .setup-skip-btn").forEach(b => b.remove());

  const retryBtn = document.createElement("button");
  retryBtn.className = "btn btn-primary setup-btn setup-retry-btn";
  retryBtn.textContent = "Retry";
  retryBtn.style.marginTop = "10px";
  retryBtn.addEventListener("click", () => {
    container.querySelectorAll(".setup-retry-btn, .setup-skip-btn").forEach(b => b.remove());
    startKnowledgeGeneration(repos);
  });

  const skipBtn = document.createElement("button");
  skipBtn.className = "btn setup-btn setup-skip-btn";
  skipBtn.textContent = "Skip to Integrations";
  skipBtn.style.marginTop = "6px";
  skipBtn.addEventListener("click", () => goToSetupStep(6));

  container.appendChild(retryBtn);
  container.appendChild(skipBtn);
}

// Step 5: Knowledge review carousel
let krFiles = [];
let krIndex = 0;
let krModified = {};

async function loadKnowledgeForReview() {
  try {
    const res = await fetch("/api/knowledge");
    const files = await res.json();
    const reviewFiles = files.filter(f => f.path !== "skills.md");
    setupState.knowledgeFileCount = reviewFiles.length;

    if (reviewFiles.length === 0) {
      goToSetupStep(6);
      return;
    }

    krFiles = [];
    for (const file of reviewFiles) {
      try {
        const fileRes = await fetch(`/api/knowledge/${file.path}`);
        const fileData = await fileRes.json();
        krFiles.push({ path: file.path, content: fileData.content });
      } catch {
        krFiles.push({ path: file.path, content: "(Failed to load)" });
      }
    }

    krIndex = 0;
    krModified = {};
    goToSetupStep(5);
    renderKnowledgeReviewFile();
  } catch (err) {
    console.error("Failed to load knowledge files:", err);
    goToSetupStep(6);
  }
}

function renderKnowledgeReviewFile() {
  const file = krFiles[krIndex];
  document.getElementById("kr-indicator").textContent = `File ${krIndex + 1} of ${krFiles.length}`;
  document.getElementById("kr-file-name").textContent = file.path;
  document.getElementById("kr-textarea").value =
    krModified[file.path] !== undefined ? krModified[file.path] : file.content;
  document.getElementById("btn-kr-prev").disabled = krIndex === 0;
  document.getElementById("btn-kr-next").disabled = krIndex === krFiles.length - 1;
  document.getElementById("kr-save-status").textContent = "";
}

document.getElementById("kr-textarea").addEventListener("input", () => {
  const file = krFiles[krIndex];
  krModified[file.path] = document.getElementById("kr-textarea").value;
});

document.getElementById("btn-kr-prev").addEventListener("click", () => {
  if (krIndex > 0) { krIndex--; renderKnowledgeReviewFile(); }
});

document.getElementById("btn-kr-next").addEventListener("click", () => {
  if (krIndex < krFiles.length - 1) { krIndex++; renderKnowledgeReviewFile(); }
});

document.getElementById("btn-kr-save").addEventListener("click", async () => {
  const file = krFiles[krIndex];
  const content = document.getElementById("kr-textarea").value;
  const statusEl = document.getElementById("kr-save-status");

  try {
    const res = await fetch(`/api/knowledge/${file.path}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (res.ok) {
      statusEl.textContent = "Saved";
      statusEl.className = "knowledge-status success";
      file.content = content;
      delete krModified[file.path];
      setTimeout(() => { if (statusEl.textContent === "Saved") statusEl.textContent = ""; }, 2000);
    } else {
      statusEl.textContent = "Save failed";
      statusEl.className = "knowledge-status error";
    }
  } catch (err) {
    statusEl.textContent = "Save failed";
    statusEl.className = "knowledge-status error";
  }
});

document.getElementById("btn-kr-done").addEventListener("click", async () => {
  const modifiedPaths = Object.keys(krModified);
  if (modifiedPaths.length > 0) {
    setSetupLoading(true, "Saving changes...");
    for (const p of modifiedPaths) {
      try {
        await fetch(`/api/knowledge/${p}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: krModified[p] }),
        });
      } catch { /* continue */ }
    }
    setSetupLoading(false);
  }
  goToSetupStep(6);
});

document.getElementById("btn-kr-skip").addEventListener("click", () => goToSetupStep(6));

// Step 6: Integrations
document.getElementById("btn-save-integrations").addEventListener("click", async () => {
  const payload = {};
  let configured = 0;

  const linearKey = document.getElementById("setup-linear-key").value.trim();
  const exaKey = document.getElementById("setup-exa-key").value.trim();
  const posthogKey = document.getElementById("setup-posthog-key").value.trim();
  const posthogHost = document.getElementById("setup-posthog-host").value.trim();
  const posthogProjectId = document.getElementById("setup-posthog-project-id").value.trim();

  if (linearKey) { payload["integration.linear_api_key"] = linearKey; configured++; }
  if (exaKey) { payload["integration.exa_api_key"] = exaKey; configured++; }
  if (posthogKey) { payload["integration.posthog_api_key"] = posthogKey; configured++; }
  if (posthogHost) payload["integration.posthog_host"] = posthogHost;
  if (posthogProjectId) payload["integration.posthog_project_id"] = posthogProjectId;

  setupState.integrationsConfigured = configured;

  if (Object.keys(payload).length > 0) {
    setSetupLoading(true, "Saving integrations...");
    try {
      await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch (err) {
      console.error("Failed to save integrations:", err);
    }
    setSetupLoading(false);
  }

  buildSetupSummary();
  goToSetupStep(7);
});

// Step 7: Summary
function buildSetupSummary() {
  const summaryEl = document.getElementById("setup-summary");
  const items = [
    { label: "GitHub Connected", detail: `${setupState.org} / Project #${setupState.selectedProject}`, done: true },
    { label: "Knowledge Files Generated", detail: `${setupState.knowledgeFileCount} file${setupState.knowledgeFileCount !== 1 ? "s" : ""}`, done: setupState.knowledgeFileCount > 0 },
    { label: "Integrations Configured", detail: `${setupState.integrationsConfigured} integration${setupState.integrationsConfigured !== 1 ? "s" : ""}`, done: setupState.integrationsConfigured > 0 },
  ];

  summaryEl.innerHTML = items.map(item => `
    <div class="summary-item">
      <span class="summary-icon ${item.done ? "summary-done" : "summary-skip"}">${item.done ? "+" : "-"}</span>
      <div class="summary-text">
        <span class="summary-label">${escapeHtml(item.label)}</span>
        <span class="summary-detail">${escapeHtml(item.detail)}</span>
      </div>
    </div>
  `).join("");
}

document.getElementById("btn-start-chat").addEventListener("click", () => {
  hideSetup();
  hideOnboardingBanner();
  sessionStorage.removeItem("onboarding-dismissed");
  setTimeout(() => checkKnowledgeOnboarding(), 1000);
});

// Reconfigure button — reset wizard and show it
function resetSetupWizard() {
  setupState.token = "";
  setupState.username = "";
  setupState.org = "";
  setupState.selectedProject = null;
  setupState.knowledgeFileCount = 0;
  setupState.integrationsConfigured = 0;
  document.getElementById("setup-token").value = "";
  document.getElementById("token-status").textContent = "";
  document.getElementById("token-status").className = "step-status";
  document.getElementById("repo-selection-list").innerHTML = "";
  document.getElementById("repo-selection-actions").style.display = "none";
  document.getElementById("repo-selection-phase").style.display = "";
  document.getElementById("knowledge-gen-phase").style.display = "none";
  document.getElementById("knowledge-progress").innerHTML = "";
  document.getElementById("knowledge-progress-status").textContent = "";
  discoveredRepos = [];
  document.getElementById("setup-linear-key").value = "";
  document.getElementById("setup-exa-key").value = "";
  document.getElementById("setup-posthog-key").value = "";
  document.getElementById("setup-posthog-host").value = "";
  document.getElementById("setup-posthog-project-id").value = "";
  krFiles = [];
  krIndex = 0;
  krModified = {};
  goToSetupStep(1);
}

document.getElementById("reconfigure-btn").addEventListener("click", () => {
  resetSetupWizard();
  showSetup();
});

// --- Main App ---

const SLASH_COMMANDS = {
  "/standup": "Analyze the current sprint and give me a daily standup report. Focus on: what's in progress, what's blocked, what was completed recently, and any risks.",
  "/analyze": "Deep analysis of the current sprint: health, risks, blockers, progress, team workload, and actionable recommendations.",
  "/estimate": "Estimate effort for the specified issue using the Fibonacci scale (1, 2, 3, 5, 8, 13). Provide reasoning, breakdown, assumptions, and risks.",
  "/review": "Review the specified pull request. Get the PR details, read the key changed files, analyze for correctness, security, performance, and architecture issues, then post a review comment on the PR via GitHub CLI. If no PR number is specified, list all open PRs across the project's repositories and summarize them.",
  "/alerts": "I want to set up proactive sprint monitoring alerts. Show me the available alert types (stuck PRs, unassigned items, sprint completion risk, stale issues, daily standup) and help me activate the ones I want. Each alert should be a recurring scheduled job that posts to Slack when issues are detected.",
  "/digest": "Generate a weekly project digest covering the last 7 days. Include: what shipped (merged PRs), what's in progress, blockers and risks, upcoming items, and sprint health metrics. Show charts for status distribution and completion progress.",
};

let currentSessionId = null;
let isStreaming = false;
let totalCost = 0;

// Model selector — persist choice
const modelSelect = document.getElementById("model-select");
try {
  const saved = localStorage.getItem("agent-model");
  if (saved && modelSelect.querySelector(`option[value="${saved}"]`)) {
    modelSelect.value = saved;
  }
} catch {}
modelSelect.addEventListener("change", () => {
  try { localStorage.setItem("agent-model", modelSelect.value); } catch {}
});

// --- Image Attachments ---

let pendingImages = []; // { data: string, media_type: string, preview: string }

function addImageFile(file) {
  if (pendingImages.length >= 5) return;
  const reader = new FileReader();
  reader.onload = () => {
    const dataUrl = reader.result;
    const base64 = dataUrl.split(",")[1];
    pendingImages.push({ data: base64, media_type: file.type, preview: dataUrl });
    renderImagePreviews();
    sendBtn.disabled = false;
  };
  reader.readAsDataURL(file);
}

function renderImagePreviews() {
  const bar = document.getElementById("image-preview-bar");
  if (pendingImages.length === 0) {
    bar.style.display = "none";
    return;
  }
  bar.style.display = "flex";
  bar.innerHTML = pendingImages
    .map(
      (img, i) => `
    <div class="image-preview-item">
      <img src="${img.preview}" alt="Attachment ${i + 1}" />
      <button class="image-remove-btn" data-index="${i}">&times;</button>
    </div>
  `
    )
    .join("");

  bar.querySelectorAll(".image-remove-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      pendingImages.splice(parseInt(btn.dataset.index), 1);
      renderImagePreviews();
      if (!inputEl.value.trim() && pendingImages.length === 0) {
        sendBtn.disabled = true;
      }
    });
  });
}

// Paste handler — intercept images from clipboard
document.getElementById("message-input").addEventListener("paste", (e) => {
  const items = e.clipboardData?.items;
  if (!items) return;
  for (const item of items) {
    if (item.type.startsWith("image/")) {
      e.preventDefault();
      const file = item.getAsFile();
      if (file) addImageFile(file);
    }
  }
});

// Drag-drop handler on input area
const inputArea = document.getElementById("input-area");
inputArea.addEventListener("dragover", (e) => {
  e.preventDefault();
  inputArea.classList.add("drag-over");
});
inputArea.addEventListener("dragleave", () => {
  inputArea.classList.remove("drag-over");
});
inputArea.addEventListener("drop", (e) => {
  e.preventDefault();
  inputArea.classList.remove("drag-over");
  for (const file of e.dataTransfer.files) {
    if (file.type.startsWith("image/")) addImageFile(file);
  }
});

// Attach button — hidden file input
document.getElementById("attach-btn").addEventListener("click", () => {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "image/*";
  input.multiple = true;
  input.onchange = () => {
    for (const file of input.files) addImageFile(file);
  };
  input.click();
});

// DOM elements
const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("message-input");
const sendBtn = document.getElementById("send-btn");
const sessionsListEl = document.getElementById("sessions-list");
const newSessionBtn = document.getElementById("new-session");
const costDisplayEl = document.getElementById("cost-display");
const chatDrawer = document.getElementById("chat-drawer");
const chatBackdrop = document.getElementById("chat-backdrop");
const chatDrawerTitle = document.getElementById("chat-drawer-title");

let currentUser = null;

// Initialize — check setup status + knowledge onboarding + user info
(async () => {
  // Fetch current user
  try {
    const meRes = await fetch("/api/auth/me");
    const meData = await meRes.json();
    if (meData.user) {
      currentUser = meData.user;
      document.getElementById("user-name").textContent = meData.user.name;
      document.getElementById("user-role").textContent = meData.user.role.toUpperCase();
      document.getElementById("user-info").style.display = "flex";

      if (meData.user.role === "admin") {
        document.getElementById("team-btn").style.display = "";
      } else {
        document.getElementById("settings-btn").style.display = "none";
        document.getElementById("reconfigure-btn").style.display = "none";
      }
    }
  } catch {}

  try {
    const res = await fetch("/api/setup/status");
    const status = await res.json();
    if (!status.configured) {
      showSetup();
    }
  } catch {
    // If check fails, continue to chat
  }

  try {
    await checkKnowledgeOnboarding();
  } catch {
    // Silently fail
  }

  loadSessions();
  loadDashboard();
})();

// Event listeners
inputEl.addEventListener("input", () => {
  sendBtn.disabled = (!inputEl.value.trim() && pendingImages.length === 0) || isStreaming;
  autoResize(inputEl);
});

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    if (!isStreaming && (inputEl.value.trim() || pendingImages.length > 0)) sendMessage();
  }
});

sendBtn.addEventListener("click", sendMessage);

newSessionBtn.addEventListener("click", () => {
  currentSessionId = null;
  chatDrawerTitle.textContent = "New Chat";
  messagesEl.innerHTML = getWelcomeHTML();
  attachQuickActions();
  openChatDrawer();
});

// Quick action buttons
function attachQuickActions() {
  document.querySelectorAll("[data-command]").forEach((btn) => {
    btn.addEventListener("click", () => {
      inputEl.value = btn.dataset.command;
      sendMessage();
    });
  });
}

document.querySelectorAll(".kbd").forEach((el) => {
  el.addEventListener("click", () => {
    inputEl.value = el.textContent;
    inputEl.focus();
  });
});

attachQuickActions();

function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 200) + "px";
}

async function loadSessions() {
  try {
    const res = await fetch("/api/sessions");
    const sessions = await res.json();
    renderSessions(sessions);
  } catch (e) {
    console.error("Failed to load sessions:", e);
  }
}

function renderSessions(sessions) {
  sessionsListEl.innerHTML = sessions
    .map(
      (s) => `
    <div class="session-item ${s.id === currentSessionId ? "active" : ""}" data-id="${s.id}">
      <div class="session-info">
        <span>${escapeHtml(s.name)}</span>
        <span class="session-date">${new Date(s.createdAt).toLocaleDateString()}</span>
      </div>
      <button class="session-delete-btn" data-id="${s.id}" title="Delete session">&times;</button>
    </div>
  `
    )
    .join("");

  sessionsListEl.querySelectorAll(".session-item").forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.target.closest(".session-delete-btn")) return;
      loadSession(el.dataset.id);
      openChatDrawer();
    });
  });

  sessionsListEl.querySelectorAll(".session-delete-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = btn.dataset.id;
      if (!confirm("Delete this session?")) return;
      try {
        await fetch(`/api/sessions/${id}`, { method: "DELETE" });
        if (currentSessionId === id) {
          currentSessionId = null;
          chatDrawerTitle.textContent = "New Chat";
          messagesEl.innerHTML = getWelcomeHTML();
          attachQuickActions();
          closeChatDrawer();
        }
        loadSessions();
      } catch (err) {
        console.error("Failed to delete session:", err);
      }
    });
  });
}

async function loadSession(id) {
  currentSessionId = id;
  document.querySelectorAll(".session-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.id === id);
    if (el.dataset.id === id) {
      const nameEl = el.querySelector(".session-info span");
      if (nameEl) chatDrawerTitle.textContent = nameEl.textContent;
    }
  });

  try {
    const res = await fetch(`/api/sessions/${id}/messages`);
    const msgs = await res.json();
    messagesEl.innerHTML = "";

    for (const msg of msgs) {
      if (msg.role === "user") {
        appendUserMessage(msg.content);
      } else if (msg.role === "assistant") {
        appendAssistantMessage(msg.content);
      }
    }

    scrollToBottom();
    updateSessionMeta();
  } catch (e) {
    console.error("Failed to load session:", e);
  }
}

async function sendMessage() {
  let text = inputEl.value.trim();
  if ((!text && pendingImages.length === 0) || isStreaming) return;

  // Handle slash commands
  const parts = text.split(" ");
  const cmd = parts[0];
  if (SLASH_COMMANDS[cmd]) {
    const args = parts.slice(1).join(" ");
    text = SLASH_COMMANDS[cmd];
    if (args) text += ` Issue: ${args}`;
  }

  // Clear welcome screen
  const welcome = messagesEl.querySelector(".welcome");
  if (welcome) welcome.remove();

  // Show user message
  appendUserMessage(inputEl.value.trim());
  inputEl.value = "";
  inputEl.style.height = "auto";
  sendBtn.disabled = true;

  // Create thinking indicator
  const thinkingDiv = document.createElement("div");
  thinkingDiv.className = "thinking-indicator";
  thinkingDiv.innerHTML = '<div class="thinking-dots"><span></span><span></span><span></span></div><span class="thinking-label">Thinking...</span>';
  thinkingDiv.style.display = "none";
  messagesEl.appendChild(thinkingDiv);

  // Create assistant message container
  const assistantDiv = document.createElement("div");
  assistantDiv.className = "message message-assistant streaming-cursor";
  assistantDiv.style.display = "none";
  messagesEl.appendChild(assistantDiv);

  // Create separate text container within assistant div
  const textContainer = document.createElement("div");
  textContainer.className = "assistant-text-content";
  assistantDiv.appendChild(textContainer);

  // Create collapsible tool container
  const toolContainer = document.createElement("div");
  toolContainer.className = "tool-container";
  toolContainer.style.display = "none";
  assistantDiv.appendChild(toolContainer);

  // Tool tracking
  const toolCalls = [];
  let toolSummary = null;
  let toolDetails = null;

  isStreaming = true;
  let fullText = "";

  try {
    const payload = { message: text, sessionId: currentSessionId, model: modelSelect.value };
    if (pendingImages.length > 0) {
      payload.images = pendingImages.map(({ data, media_type }) => ({ data, media_type }));
    }
    pendingImages = [];
    renderImagePreviews();

    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          const data = JSON.parse(line.slice(6));
          const eventLine = lines[lines.indexOf(line) - 1];
          const eventType = eventLine?.startsWith("event: ")
            ? eventLine.slice(7)
            : "delta";

          if (eventType === "thinking") {
            thinkingDiv.style.display = "flex";
            thinkingDiv.querySelector(".thinking-label").textContent = "Thinking...";
            scrollToBottom();
          } else if (eventType === "typing") {
            thinkingDiv.querySelector(".thinking-label").textContent = "Typing...";
            scrollToBottom();
          } else if (eventType === "delta" || !eventLine) {
            if (data.content) {
              thinkingDiv.style.display = "none";
              assistantDiv.style.display = "";
              fullText += data.content;

              // Update only the text container, leaving charts intact
              const textContainer = assistantDiv.querySelector('.assistant-text-content');
              if (textContainer) {
                textContainer.innerHTML = renderMarkdown(fullText);
              } else {
                // Fallback if text container doesn't exist
                assistantDiv.innerHTML = renderMarkdown(fullText);
              }

              scrollToBottom();
            }
          } else if (eventType === "visualization") {
            thinkingDiv.style.display = "none";
            assistantDiv.style.display = "";
            if (data.tool === "render_chart") {
              try {
                const chartConfig = JSON.parse(data.input.config);
                renderChartElement(assistantDiv, chartConfig);
                // Embed marker in fullText so it persists in DB
                fullText += `\n<!--CHART:${data.input.config}-->\n`;
              } catch (e) {
                console.error("[viz] Failed to parse chart config:", e);
              }
            } else if (data.tool === "render_diagram") {
              renderMermaidElement(assistantDiv, data.input);
              // Embed marker in fullText so it persists in DB
              fullText += `\n<!--DIAGRAM:${JSON.stringify(data.input)}-->\n`;
            }
            scrollToBottom();
          } else if (eventType === "dashboard_update") {
            handleDashboardUpdate(data);
          } else if (eventType === "tool") {
            // Track tool call
            toolCalls.push(data.tool);

            // Create/update tool summary
            if (!toolSummary) {
              toolSummary = document.createElement("div");
              toolSummary.className = "tool-summary";
              toolSummary.innerHTML = `
                <div class="tool-summary-header">
                  <span class="tool-count">Used ${toolCalls.length} tool${toolCalls.length > 1 ? 's' : ''}</span>
                  <button class="tool-toggle-btn" data-expanded="false">▼ Show details</button>
                </div>
              `;
              toolContainer.appendChild(toolSummary);

              toolDetails = document.createElement("div");
              toolDetails.className = "tool-details";
              toolDetails.style.display = "none";
              toolContainer.appendChild(toolDetails);

              // Add toggle functionality
              const toggleBtn = toolSummary.querySelector('.tool-toggle-btn');
              toggleBtn.addEventListener('click', () => {
                const expanded = toggleBtn.dataset.expanded === 'true';
                if (expanded) {
                  toolDetails.style.display = 'none';
                  toggleBtn.textContent = '▼ Show details';
                  toggleBtn.dataset.expanded = 'false';
                } else {
                  toolDetails.style.display = 'block';
                  toggleBtn.textContent = '▲ Hide details';
                  toggleBtn.dataset.expanded = 'true';
                }
              });

              toolContainer.style.display = "block";
            } else {
              // Update count
              toolSummary.querySelector('.tool-count').textContent = `Used ${toolCalls.length} tool${toolCalls.length > 1 ? 's' : ''}`;
            }

            // Add individual tool indicator to details
            const toolEl = document.createElement("div");
            toolEl.className = "tool-indicator";
            const detail = data.detail ? ` <span class="tool-detail">${escapeHtml(data.detail)}</span>` : "";
            toolEl.innerHTML = `<span class="spinner"></span> ${escapeHtml(data.tool)}${detail}`;
            toolDetails.appendChild(toolEl);
            scrollToBottom();
          } else if (eventType === "done") {
            if (data.sessionId) {
              currentSessionId = data.sessionId;
            }
            if (data.costUsd) {
              totalCost += data.costUsd;
              costDisplayEl.textContent = `COST: $${totalCost.toFixed(4)}`;
            }
          } else if (eventType === "error") {
            assistantDiv.innerHTML += `<p style="color: var(--red)">Error: ${escapeHtml(data.message)}</p>`;
          }
        }
      }
    }
  } catch (e) {
    assistantDiv.innerHTML += `<p style="color: var(--red)">Connection error: ${escapeHtml(e.message)}</p>`;
  }

  thinkingDiv.remove();
  assistantDiv.style.display = "";
  assistantDiv.classList.remove("streaming-cursor");
  isStreaming = false;
  sendBtn.disabled = !inputEl.value.trim() && pendingImages.length === 0;
  loadSessions();
  updateSessionMeta();
}

function appendUserMessage(text) {
  const div = document.createElement("div");
  div.className = "message";
  div.innerHTML = `<div class="message-user">${escapeHtml(text)}</div>`;
  messagesEl.appendChild(div);
  scrollToBottom();
}

function appendAssistantMessage(text) {
  const div = document.createElement("div");
  div.className = "message message-assistant";

  // Extract visualization markers before rendering markdown
  const chartMarkers = [];
  const diagramMarkers = [];
  const cleanText = text.replace(/\n?<!--CHART:([\s\S]*?)-->\n?/g, (_, config) => {
    chartMarkers.push(config);
    return "";
  }).replace(/\n?<!--DIAGRAM:([\s\S]*?)-->\n?/g, (_, config) => {
    diagramMarkers.push(config);
    return "";
  });

  // Render the text content
  div.innerHTML = renderMarkdown(cleanText);
  messagesEl.appendChild(div);

  // Re-render embedded charts
  for (const configStr of chartMarkers) {
    try {
      const chartConfig = JSON.parse(configStr);
      renderChartElement(div, chartConfig);
    } catch (e) {
      console.error("[viz] Failed to restore chart:", e);
    }
  }

  // Re-render embedded diagrams
  for (const configStr of diagramMarkers) {
    try {
      const diagramConfig = JSON.parse(configStr);
      renderMermaidElement(div, diagramConfig);
    } catch (e) {
      console.error("[viz] Failed to restore diagram:", e);
    }
  }

  scrollToBottom();
}

function renderMarkdown(text) {
  try {
    let html = marked.parse(text, { breaks: true, gfm: true });
    // Style images in responses
    html = html.replace(/<img /g, '<img loading="lazy" style="max-width:100%;border-radius:4px;" ');
    return html;
  } catch {
    return escapeHtml(text);
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function getWelcomeHTML() {
  return `
    <div class="welcome">
      <h3>PM Agent</h3>
      <p>Connected to your GitHub Project. Ask me about sprint status, estimates, or anything about your project.</p>
      <div class="quick-actions">
        <button class="btn btn-ghost" data-command="/standup">Sprint Standup</button>
        <button class="btn btn-ghost" data-command="/analyze">Deep Analysis</button>
        <button class="btn btn-ghost" data-command="What issues are in progress?">In Progress</button>
      </div>
    </div>
  `;
}

// --- Knowledge Hub ---

const knowledgeOverlay = document.getElementById("knowledge-overlay");
const knowledgeFileList = document.getElementById("knowledge-file-list");
const knowledgeTextarea = document.getElementById("knowledge-textarea");
const knowledgeFilePath = document.getElementById("knowledge-file-path");
const knowledgeStatus = document.getElementById("knowledge-status");
const knowledgeEditorEmpty = document.getElementById("knowledge-editor-empty");
const knowledgeEditorActive = document.getElementById("knowledge-editor-active");

let knowledgeCurrentFile = null;

document.getElementById("knowledge-hub-btn").addEventListener("click", () => {
  knowledgeOverlay.classList.remove("hidden");
  loadKnowledgeFiles();
});

document.getElementById("knowledge-close-btn").addEventListener("click", () => {
  knowledgeOverlay.classList.add("hidden");
  knowledgeCurrentFile = null;
});

document.getElementById("knowledge-new-btn").addEventListener("click", () => {
  const name = prompt("File path (e.g. notes.md or repos/new-repo.md):");
  if (!name) return;
  const filePath = name.endsWith(".md") ? name : name + ".md";
  knowledgeCurrentFile = filePath;
  knowledgeFilePath.textContent = filePath;
  knowledgeTextarea.value = "";
  knowledgeEditorEmpty.classList.add("hidden");
  knowledgeEditorActive.classList.remove("hidden");
  setKnowledgeStatus("New file — edit and save", "");
});

document.getElementById("knowledge-save-btn").addEventListener("click", saveKnowledgeFile);

document.getElementById("knowledge-delete-btn").addEventListener("click", async () => {
  if (!knowledgeCurrentFile) return;
  if (!confirm(`Delete ${knowledgeCurrentFile}?`)) return;
  try {
    const res = await fetch(`/api/knowledge/${knowledgeCurrentFile}`, { method: "DELETE" });
    const data = await res.json();
    if (!res.ok) {
      setKnowledgeStatus(data.error || "Delete failed", "error");
      return;
    }
    knowledgeCurrentFile = null;
    knowledgeEditorActive.classList.add("hidden");
    knowledgeEditorEmpty.classList.remove("hidden");
    loadKnowledgeFiles();
  } catch (err) {
    setKnowledgeStatus("Delete failed: " + err.message, "error");
  }
});

async function loadKnowledgeFiles() {
  try {
    const res = await fetch("/api/knowledge");
    const files = await res.json();
    knowledgeFileList.innerHTML = files
      .map((f) => {
        const isActive = f.path === knowledgeCurrentFile;
        const sizeKb = (f.size / 1024).toFixed(1);
        return `<div class="knowledge-file-item ${isActive ? "active" : ""}" data-path="${escapeHtml(f.path)}">
          <span class="knowledge-file-name">${escapeHtml(f.path)}</span>
          <span class="knowledge-file-size">${sizeKb}k</span>
        </div>`;
      })
      .join("");

    knowledgeFileList.querySelectorAll(".knowledge-file-item").forEach((el) => {
      el.addEventListener("click", () => loadKnowledgeFile(el.dataset.path));
    });
  } catch (err) {
    knowledgeFileList.innerHTML = '<div style="padding:12px;color:var(--red)">Failed to load files</div>';
  }
}

async function loadKnowledgeFile(filePath) {
  try {
    const res = await fetch(`/api/knowledge/${filePath}`);
    const data = await res.json();
    if (!res.ok) {
      setKnowledgeStatus(data.error || "Failed to load", "error");
      return;
    }
    knowledgeCurrentFile = filePath;
    knowledgeFilePath.textContent = filePath;
    knowledgeTextarea.value = data.content;
    knowledgeEditorEmpty.classList.add("hidden");
    knowledgeEditorActive.classList.remove("hidden");
    setKnowledgeStatus("", "");
    loadKnowledgeFiles(); // refresh active state
  } catch (err) {
    setKnowledgeStatus("Load failed: " + err.message, "error");
  }
}

async function saveKnowledgeFile() {
  if (!knowledgeCurrentFile) return;
  try {
    const res = await fetch(`/api/knowledge/${knowledgeCurrentFile}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: knowledgeTextarea.value }),
    });
    if (res.ok) {
      setKnowledgeStatus("Saved", "success");
      loadKnowledgeFiles();
    } else {
      const data = await res.json();
      setKnowledgeStatus(data.error || "Save failed", "error");
    }
  } catch (err) {
    setKnowledgeStatus("Save failed: " + err.message, "error");
  }
}

function setKnowledgeStatus(text, type) {
  knowledgeStatus.textContent = text;
  knowledgeStatus.className = "knowledge-status" + (type ? " " + type : "");
  if (type === "success") {
    setTimeout(() => {
      if (knowledgeStatus.textContent === text) knowledgeStatus.textContent = "";
    }, 2000);
  }
}

// --- Onboarding Banner ---

async function checkKnowledgeOnboarding() {
  if (sessionStorage.getItem("onboarding-dismissed") === "true") return;

  const res = await fetch("/api/knowledge");
  const files = await res.json();

  // Show banner if 0 files or only skills.md
  const nonSkillFiles = files.filter((f) => f.path !== "skills.md");
  if (nonSkillFiles.length === 0) {
    showOnboardingBanner();
  }
}

function showOnboardingBanner() {
  document.getElementById("onboarding-banner").classList.remove("hidden");
}

function hideOnboardingBanner() {
  document.getElementById("onboarding-banner").classList.add("hidden");
}

document.getElementById("banner-setup-btn").addEventListener("click", () => {
  resetSetupWizard();
  showSetup();
});

document.getElementById("banner-dismiss-btn").addEventListener("click", () => {
  hideOnboardingBanner();
  sessionStorage.setItem("onboarding-dismissed", "true");
});

// --- Settings ---

const SETTINGS_FIELDS = {
  "integration.exa_api_key": "setting-exa-key",
  "integration.posthog_api_key": "setting-posthog-key",
  "integration.posthog_host": "setting-posthog-host",
  "integration.posthog_project_id": "setting-posthog-project-id",
  "integration.linear_api_key": "setting-linear-key",
  "slack.allowed_users": "setting-slack-users",
  "slack.allowed_channels": "setting-slack-channels",
};

const SENSITIVE_SETTINGS = [
  "integration.exa_api_key",
  "integration.posthog_api_key",
  "integration.linear_api_key",
];

const ARRAY_SETTINGS = ["slack.allowed_users", "slack.allowed_channels"];

let maskedOriginals = {};

document.getElementById("settings-btn").addEventListener("click", () => {
  document.getElementById("settings-overlay").classList.remove("hidden");
  loadSettings();
});

document.getElementById("settings-close-btn").addEventListener("click", () => {
  document.getElementById("settings-overlay").classList.add("hidden");
});

async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    const data = await res.json();
    maskedOriginals = {};

    for (const [key, elId] of Object.entries(SETTINGS_FIELDS)) {
      const el = document.getElementById(elId);
      if (!el) continue;

      let value = data[key];
      if (value === null || value === undefined) value = "";

      if (ARRAY_SETTINGS.includes(key) && Array.isArray(value)) {
        el.value = value.join(", ");
      } else {
        el.value = String(value);
      }

      if (SENSITIVE_SETTINGS.includes(key) && String(value).startsWith("****")) {
        maskedOriginals[key] = String(value);
      }
    }
  } catch (err) {
    setSettingsStatus("Failed to load: " + err.message, "error");
  }
}

document.getElementById("settings-save-btn").addEventListener("click", async () => {
  const payload = {};

  for (const [key, elId] of Object.entries(SETTINGS_FIELDS)) {
    const el = document.getElementById(elId);
    if (!el || el.disabled) continue;

    let value = el.value.trim();

    // Skip unchanged masked fields
    if (SENSITIVE_SETTINGS.includes(key) && maskedOriginals[key] && value === maskedOriginals[key]) {
      continue;
    }

    // Convert array fields
    if (ARRAY_SETTINGS.includes(key)) {
      if (value === "" || value.toLowerCase() === "all") {
        value = null; // delete = revert to default (allow all)
      } else {
        value = value.split(",").map(s => s.trim()).filter(Boolean);
      }
    }

    // Empty = delete (revert to env)
    if (value === "") value = null;

    payload[key] = value;
  }

  try {
    const res = await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (res.ok) {
      setSettingsStatus("Settings saved", "success");
      setTimeout(() => loadSettings(), 500);
    } else {
      setSettingsStatus("Save failed", "error");
    }
  } catch (err) {
    setSettingsStatus("Save failed: " + err.message, "error");
  }
});

function setSettingsStatus(text, type) {
  const el = document.getElementById("settings-status");
  el.textContent = text;
  el.className = "settings-save-status" + (type ? " " + type : "");
  if (type === "success") {
    setTimeout(() => { if (el.textContent === text) el.textContent = ""; }, 3000);
  }
}

// --- Team Panel ---

document.getElementById("team-btn")?.addEventListener("click", () => {
  document.getElementById("team-overlay").classList.remove("hidden");
  loadTeamMembers();
});

document.getElementById("team-close-btn")?.addEventListener("click", () => {
  document.getElementById("team-overlay").classList.add("hidden");
});

async function loadTeamMembers() {
  try {
    const res = await fetch("/api/team");
    if (!res.ok) return;
    const members = await res.json();
    const listEl = document.getElementById("team-members-list");
    listEl.innerHTML = members.map((m) => `
      <div class="team-member-item">
        <div class="team-member-info">
          <span class="team-member-name">${escapeHtml(m.name)}</span>
          <span class="team-member-role">${m.role.toUpperCase()}</span>
        </div>
        ${m.id !== currentUser?.id && m.role !== "admin"
          ? `<button class="team-remove-btn" data-id="${m.id}" title="Remove">&times;</button>`
          : ""}
      </div>
    `).join("");

    listEl.querySelectorAll(".team-remove-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("Remove this team member?")) return;
        await fetch(`/api/team/${btn.dataset.id}`, { method: "DELETE" });
        loadTeamMembers();
      });
    });
  } catch (err) {
    console.error("Failed to load team:", err);
  }
}

document.getElementById("team-invite-btn")?.addEventListener("click", async () => {
  try {
    const res = await fetch("/api/team/invites", { method: "POST" });
    const data = await res.json();
    const link = window.location.origin + data.link;
    document.getElementById("invite-link").value = link;
    document.getElementById("invite-result").style.display = "flex";
  } catch (err) {
    alert("Failed to create invite: " + err.message);
  }
});

document.getElementById("invite-copy-btn")?.addEventListener("click", () => {
  const input = document.getElementById("invite-link");
  navigator.clipboard.writeText(input.value);
  const btn = document.getElementById("invite-copy-btn");
  btn.textContent = "Copied!";
  setTimeout(() => { btn.textContent = "Copy"; }, 2000);
});

// --- Chat Drawer ---

function openChatDrawer() {
  chatDrawer.classList.add("open");
  chatBackdrop.classList.remove("hidden");
  requestAnimationFrame(() => chatBackdrop.classList.add("open"));
  inputEl.focus();
}

function closeChatDrawer() {
  chatDrawer.classList.remove("open");
  chatBackdrop.classList.remove("open");
  setTimeout(() => chatBackdrop.classList.add("hidden"), 250);
}

document.getElementById("chat-drawer-close").addEventListener("click", closeChatDrawer);
chatBackdrop.addEventListener("click", closeChatDrawer);

// --- Chat Drawer Resize ---

(function initDrawerResize() {
  const handle = document.getElementById("chat-resize-handle");
  if (!handle) return;

  let isResizing = false;

  handle.addEventListener("mousedown", (e) => {
    e.preventDefault();
    isResizing = true;
    chatDrawer.classList.add("resizing");
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  });

  document.addEventListener("mousemove", (e) => {
    if (!isResizing) return;
    const newWidth = window.innerWidth - e.clientX;
    const clamped = Math.max(360, Math.min(newWidth, window.innerWidth * 0.8));
    chatDrawer.style.width = clamped + "px";
  });

  document.addEventListener("mouseup", () => {
    if (!isResizing) return;
    isResizing = false;
    chatDrawer.classList.remove("resizing");
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    // Persist width
    try { localStorage.setItem("chat-drawer-width", chatDrawer.style.width); } catch {}
  });

  // Restore saved width
  try {
    const saved = localStorage.getItem("chat-drawer-width");
    if (saved) chatDrawer.style.width = saved;
  } catch {}
})();

// --- Dashboard ---

let dashboardItems = [];
let activeTabId = "project"; // "project" = built-in, or a tab ID
let dashboardTabsList = []; // cached tabs from server

document.getElementById("dashboard-refresh-btn").addEventListener("click", loadDashboard);

const filterEls = {
  sprint: document.getElementById("filter-sprint"),
  assignee: document.getElementById("filter-assignee"),
  priority: document.getElementById("filter-priority"),
  status: document.getElementById("filter-status"),
  repo: document.getElementById("filter-repo"),
};

Object.values(filterEls).forEach((sel) =>
  sel.addEventListener("change", applyDashboardFilters)
);

function populateFilters(filters) {
  const populate = (sel, values) => {
    sel.innerHTML = '<option value="">All</option>';
    for (const v of values) {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      sel.appendChild(opt);
    }
  };
  populate(filterEls.sprint, filters.sprints || []);
  populate(filterEls.assignee, filters.assignees || []);
  populate(filterEls.priority, filters.priorities || []);
  populate(filterEls.status, filters.statuses || []);
  populate(filterEls.repo, filters.repositories || []);
}

function computeClientStats(items) {
  const statusCounts = {};
  const assigneeWorkload = {};
  const priorityCounts = {};
  const inProgress = [];

  for (const item of items) {
    const status = item.status || "No Status";
    statusCounts[status] = (statusCounts[status] || 0) + 1;
    if (status.toLowerCase() === "in progress") inProgress.push(item);

    const priority = item.priority || "No Priority";
    priorityCounts[priority] = (priorityCounts[priority] || 0) + 1;

    const assignees = item.assignees && item.assignees.length > 0 ? item.assignees : ["Unassigned"];
    for (const a of assignees) {
      if (!assigneeWorkload[a]) assigneeWorkload[a] = {};
      assigneeWorkload[a][status] = (assigneeWorkload[a][status] || 0) + 1;
    }
  }

  const sprintBreakdown = {};
  for (const item of items) {
    const sprint = item.custom_fields?.sprint;
    if (sprint == null) continue;
    const sprintKey = String(sprint);
    const st = item.status || "No Status";
    if (!sprintBreakdown[sprintKey]) sprintBreakdown[sprintKey] = {};
    sprintBreakdown[sprintKey][st] = (sprintBreakdown[sprintKey][st] || 0) + 1;
  }

  const total = items.length;
  const done = items.filter(
    (i) => (i.status || "").toLowerCase() === "done" || i.state === "CLOSED"
  ).length;
  const blocked = items.filter(
    (i) => (i.status || "").toLowerCase() === "blocked"
  ).length;

  return {
    statusCounts,
    assigneeWorkload,
    inProgress,
    priorityCounts,
    sprintBreakdown,
    overview: {
      total,
      done,
      completionPct: total > 0 ? Math.round((done / total) * 100) : 0,
      inProgressCount: inProgress.length,
      blocked,
    },
  };
}

function ciEquals(a, b) {
  return String(a).toLowerCase() === String(b).toLowerCase();
}

function applyDashboardFilters() {
  if (activeTabId !== "project") return; // filters only apply to project tab
  const sprint = filterEls.sprint.value;
  const assignee = filterEls.assignee.value;
  const priority = filterEls.priority.value;
  const status = filterEls.status.value;
  const repo = filterEls.repo.value;

  let filtered = dashboardItems;
  if (sprint) filtered = filtered.filter((i) => ciEquals(i.custom_fields?.sprint, sprint));
  if (assignee) filtered = filtered.filter((i) => i.assignees && i.assignees.some((a) => ciEquals(a, assignee)));
  if (priority) filtered = filtered.filter((i) => ciEquals(i.priority, priority));
  if (status) filtered = filtered.filter((i) => ciEquals(i.status, status));
  if (repo) filtered = filtered.filter((i) => ciEquals(i.repository, repo));

  renderDashboard(computeClientStats(filtered));
}

// --- Tab Bar ---

function renderTabBar(tabs) {
  const container = document.getElementById("dashboard-tabs");
  container.innerHTML = "";

  // Built-in Project tab (always first, non-deletable)
  const projectTab = document.createElement("button");
  projectTab.className = `dashboard-tab${activeTabId === "project" ? " active" : ""}`;
  projectTab.dataset.tabId = "project";
  projectTab.innerHTML = `<span>Project</span>`;
  projectTab.addEventListener("click", () => switchTab("project"));
  container.appendChild(projectTab);

  // Agent-created tabs
  for (const tab of tabs) {
    const tabEl = document.createElement("button");
    tabEl.className = `dashboard-tab${activeTabId === tab.id ? " active" : ""}`;
    tabEl.dataset.tabId = tab.id;
    const filterBadge = tab.filters ? `<span class="dashboard-tab-filter" title="${escapeHtml(Object.entries(tab.filters).map(([k,v]) => `${k}=${v}`).join(", "))}">F</span>` : "";
    const refreshBtn = tab.refreshPrompt
      ? `<button class="tab-refresh-btn" data-tab-id="${tab.id}" title="${tab.lastRefreshedAt ? `Last updated: ${formatTimeAgo(new Date(tab.lastRefreshedAt))}` : 'Refresh tab data'}">&#x21bb;</button>`
      : "";
    tabEl.innerHTML = `<span>${escapeHtml(tab.name)}</span>${filterBadge}${refreshBtn}<button class="dashboard-tab-delete" title="Delete tab">&times;</button>`;
    tabEl.addEventListener("click", (e) => {
      if (e.target.closest(".dashboard-tab-delete") || e.target.closest(".tab-refresh-btn")) return;
      switchTab(tab.id);
    });
    tabEl.querySelector(".dashboard-tab-delete").addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm(`Delete tab "${tab.name}" and all its widgets?`)) return;
      await fetch(`/api/dashboard/tabs/${tab.id}`, { method: "DELETE" });
      if (activeTabId === tab.id) activeTabId = "project";
      await loadDashboard();
    });
    const refreshBtnEl = tabEl.querySelector(".tab-refresh-btn");
    if (refreshBtnEl) {
      refreshBtnEl.addEventListener("click", async (e) => {
        e.stopPropagation();
        refreshBtnEl.classList.add("loading");
        try {
          await fetch(`/api/dashboard/tabs/${tab.id}/refresh`, { method: "POST" });
          // Reload after a short delay to let the refresh agent work
          setTimeout(() => loadDashboard(), 3000);
        } catch (err) {
          console.error("Refresh failed:", err);
        } finally {
          setTimeout(() => refreshBtnEl.classList.remove("loading"), 2000);
        }
      });
    }
    container.appendChild(tabEl);
  }
}

async function switchTab(tabId) {
  activeTabId = tabId;
  const grid = document.getElementById("widget-grid");
  const filtersEl = document.getElementById("dashboard-filters");

  // Update active state on tab bar
  document.querySelectorAll(".dashboard-tab").forEach((el) => {
    el.classList.toggle("active", el.dataset.tabId === tabId);
  });

  if (tabId === "project") {
    // Show filters, load GitHub data
    filtersEl.style.display = "";
    document.getElementById("dashboard-fetched-at").textContent = "LOADING...";
    try {
      const res = await fetch("/api/dashboard");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      dashboardItems = data.items || [];
      populateFilters(data.filters || {});
      document.getElementById("dashboard-fetched-at").textContent =
        `FETCHED: ${new Date(data.fetchedAt).toLocaleTimeString()}`;
      renderDashboard(data.stats);
      loadActivity();
    } catch (err) {
      grid.innerHTML = `<div class="widget-grid-empty" style="color:var(--red)">Error: ${escapeHtml(err.message)}</div>`;
    }
  } else {
    // Custom tab — check for filters and widgets
    filtersEl.style.display = "none";
    const tabMeta = dashboardTabsList.find((t) => t.id === tabId);
    const tabFilters = tabMeta?.filters || null;

    try {
      const res = await fetch(`/api/dashboard/tabs/${tabId}/widgets`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const widgets = data.widgets || [];

      if (widgets.length > 0) {
        // Tab has explicit widgets — render them
        const updatedInfo = tabMeta?.lastRefreshedAt
          ? `UPDATED: ${formatTimeAgo(new Date(tabMeta.lastRefreshedAt))}`
          : "AGENT TAB";
        document.getElementById("dashboard-fetched-at").textContent = updatedInfo;
        renderWidgetGrid(widgets);
      } else if (tabFilters) {
        // Filtered tab with no explicit widgets — load GitHub data, apply filters, auto-generate
        document.getElementById("dashboard-fetched-at").textContent = "LOADING FILTERED DATA...";
        const ghRes = await fetch("/api/dashboard");
        if (!ghRes.ok) throw new Error(`HTTP ${ghRes.status}`);
        const ghData = await ghRes.json();
        let items = ghData.items || [];

        // Apply tab filters (case-insensitive)
        if (tabFilters.sprint) items = items.filter((i) => ciEquals(i.custom_fields?.sprint, tabFilters.sprint));
        if (tabFilters.assignee) items = items.filter((i) => i.assignees && i.assignees.some((a) => ciEquals(a, tabFilters.assignee)));
        if (tabFilters.priority) items = items.filter((i) => ciEquals(i.priority, tabFilters.priority));
        if (tabFilters.status) items = items.filter((i) => ciEquals(i.status, tabFilters.status));
        if (tabFilters.repo) items = items.filter((i) => ciEquals(i.repository, tabFilters.repo));

        const filterDesc = Object.entries(tabFilters).map(([k, v]) => `${k}=${v}`).join(", ");
        document.getElementById("dashboard-fetched-at").textContent =
          `FILTERED: ${filterDesc} (${items.length} items)`;
        renderDashboard(computeClientStats(items));
      } else {
        // No widgets, no filters — empty tab
        document.getElementById("dashboard-fetched-at").textContent = "AGENT TAB";
        renderWidgetGrid([]);
      }
    } catch (err) {
      grid.innerHTML = `<div class="widget-grid-empty" style="color:var(--red)">Error: ${escapeHtml(err.message)}</div>`;
    }
  }
}

async function loadDashboard() {
  const loading = document.getElementById("dashboard-loading");
  const error = document.getElementById("dashboard-error");
  const grid = document.getElementById("widget-grid");

  loading.classList.remove("hidden");
  error.classList.add("hidden");
  if (grid) grid.style.opacity = "0.4";

  try {
    // Load tabs
    const tabsRes = await fetch("/api/dashboard/tabs");
    const tabsData = await tabsRes.json();
    dashboardTabsList = tabsData.tabs || [];
    renderTabBar(dashboardTabsList);

    // If active tab is a custom tab that was deleted, fall back to project
    if (activeTabId !== "project" && !dashboardTabsList.find((t) => t.id === activeTabId)) {
      activeTabId = "project";
      renderTabBar(dashboardTabsList);
    }

    // Load content for active tab
    await switchTab(activeTabId);
  } catch (err) {
    error.textContent = `Dashboard error: ${err.message}`;
    error.classList.remove("hidden");
  } finally {
    loading.classList.add("hidden");
    if (grid) grid.style.opacity = "";
  }
}

const STATUS_COLORS = {
  "Done": "#00c853",
  "In Progress": "#e8912d",
  "In progress": "#e8912d",
  "Todo": "#58a6ff",
  "Blocked": "#ff3d3d",
  "blocked": "#ff3d3d",
  "No Status": "#484f58",
};

// --- Widget Grid System ---

function renderWidgetGrid(widgets) {
  const grid = document.getElementById("widget-grid");
  if (!grid) return;
  grid.innerHTML = "";

  if (!widgets || widgets.length === 0) {
    grid.innerHTML = '<div class="widget-grid-empty">No widgets — ask the agent to set up your dashboard</div>';
    return;
  }

  widgets
    .sort((a, b) => (a.position || 0) - (b.position || 0))
    .forEach((widget) => {
      const el = createWidgetElement(widget);
      grid.appendChild(el);
    });
}

function createWidgetElement(widget) {
  const div = document.createElement("div");
  div.className = `widget widget-${widget.size || "half"}`;
  div.id = `widget-${widget.id}`;
  div.dataset.widgetId = widget.id;

  // Stat cards have a simpler layout
  if (widget.type === "stat-card") {
    const config = typeof widget.config === "string" ? JSON.parse(widget.config) : widget.config;
    const colorClass = config.color && config.color !== "default" ? `color-${config.color}` : "";
    div.innerHTML = `
      <div class="widget-stat">
        <span class="widget-stat-label">${escapeHtml(widget.title)}</span>
        <span class="widget-stat-value ${colorClass}">${escapeHtml(String(config.value || "--"))}</span>
        ${config.trend ? `<span class="widget-stat-trend">${escapeHtml(config.trend)}</span>` : ""}
      </div>
    `;
    return div;
  }

  div.innerHTML = `
    <div class="widget-header"><span>${escapeHtml(widget.title)}</span></div>
    <div class="widget-body"></div>
  `;

  const body = div.querySelector(".widget-body");
  const config = typeof widget.config === "string" ? JSON.parse(widget.config) : widget.config;

  const renderer = WIDGET_RENDERERS[widget.type];
  if (renderer) renderer(body, config);

  return div;
}

const WIDGET_RENDERERS = {
  chart: renderChartWidget,
  table: renderTableWidget,
  list: renderListWidget,
  markdown: renderMarkdownWidget,
};

function renderChartWidget(container, config) {
  container.style.minHeight = "200px";
  renderChartElement(container, config);
}

function renderTableWidget(container, config) {
  if (!config.headers || !config.rows) {
    container.innerHTML = '<div style="color: var(--text-muted); font-size: 11px;">No data</div>';
    return;
  }
  container.innerHTML = `
    <table class="widget-table">
      <thead><tr>${config.headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("")}</tr></thead>
      <tbody>${config.rows.map((row) =>
        `<tr>${row.map((cell) => `<td>${escapeHtml(String(cell))}</td>`).join("")}</tr>`
      ).join("")}</tbody>
    </table>
  `;
}

function renderListWidget(container, config) {
  if (!config.items || !config.items.length) {
    container.innerHTML = '<div style="color: var(--text-muted); font-size: 11px;">Empty list</div>';
    return;
  }
  container.innerHTML = `
    <ul class="widget-list">
      ${config.items.map((item) =>
        `<li${item.color ? ` style="color:${item.color}"` : ""}>${escapeHtml(item.text)}</li>`
      ).join("")}
    </ul>
  `;
}

function renderMarkdownWidget(container, config) {
  container.innerHTML = `<div class="widget-markdown">${renderMarkdown(config.content || "")}</div>`;
}

// Generate default widgets from GitHub project stats
function generateDefaultWidgets(stats) {
  const statusLabels = Object.keys(stats.statusCounts);
  const statusData = Object.values(stats.statusCounts);
  const statusColors = statusLabels.map((l, i) => STATUS_COLORS[l] || CHART_COLORS[i % CHART_COLORS.length]);

  const priorityLabels = Object.keys(stats.priorityCounts);
  const priorityData = Object.values(stats.priorityCounts);

  const assignees = Object.keys(stats.assigneeWorkload);
  const allStatuses = [...new Set(assignees.flatMap((a) => Object.keys(stats.assigneeWorkload[a])))];
  const workloadDatasets = allStatuses.map((status, i) => ({
    label: status,
    data: assignees.map((a) => stats.assigneeWorkload[a][status] || 0),
    backgroundColor: STATUS_COLORS[status] || CHART_COLORS[i % CHART_COLORS.length],
  }));

  const widgets = [
    { id: "stat-total", type: "stat-card", title: "Total Items", size: "quarter", position: 0, config: { value: String(stats.overview.total) } },
    { id: "stat-completion", type: "stat-card", title: "Completion", size: "quarter", position: 1, config: { value: `${stats.overview.completionPct}%` } },
    { id: "stat-progress", type: "stat-card", title: "In Progress", size: "quarter", position: 2, config: { value: String(stats.overview.inProgressCount) } },
    { id: "stat-blocked", type: "stat-card", title: "Blocked", size: "quarter", position: 3, config: { value: String(stats.overview.blocked), color: "red" } },
    { id: "chart-status", type: "chart", title: "Status Distribution", size: "half", position: 4, config: { type: "doughnut", data: { labels: statusLabels, datasets: [{ label: "Items", data: statusData, backgroundColor: statusColors }] } } },
    { id: "chart-priority", type: "chart", title: "Priority Breakdown", size: "half", position: 5, config: { type: "bar", data: { labels: priorityLabels, datasets: [{ label: "Items", data: priorityData }] } } },
    { id: "chart-workload", type: "chart", title: "Assignee Workload", size: "full", position: 6, config: { type: "bar", data: { labels: assignees, datasets: workloadDatasets }, options: { scales: { x: { stacked: true }, y: { stacked: true } } } } },
  ];

  // Sprint progress if available
  if (stats.sprintBreakdown && Object.keys(stats.sprintBreakdown).length > 0) {
    const sprints = Object.keys(stats.sprintBreakdown).sort((a, b) => Number(a) - Number(b));
    const allSprintStatuses = [...new Set(sprints.flatMap((s) => Object.keys(stats.sprintBreakdown[s])))];
    const sprintDatasets = allSprintStatuses.map((status, i) => ({
      label: status,
      data: sprints.map((s) => stats.sprintBreakdown[s][status] || 0),
      backgroundColor: STATUS_COLORS[status] || CHART_COLORS[i % CHART_COLORS.length],
    }));
    widgets.push({
      id: "chart-sprint", type: "chart", title: "Sprint Progress", size: "full", position: 7,
      config: { type: "bar", data: { labels: sprints.map((s) => `Sprint ${s}`), datasets: sprintDatasets }, options: { indexAxis: "y", scales: { x: { stacked: true }, y: { stacked: true } } } },
    });
  }

  // In-progress table
  if (stats.inProgress && stats.inProgress.length > 0) {
    widgets.push({
      id: "table-progress", type: "table", title: "In Progress Items", size: "full", position: 8,
      config: {
        headers: ["#", "Title", "Assignees", "Repo", "Priority"],
        rows: stats.inProgress.map((item) => [
          String(item.number || "--"),
          item.title,
          item.assignees.length ? item.assignees.join(", ") : "Unassigned",
          item.repository || "--",
          String(item.priority || "--"),
        ]),
      },
    });
  }

  return widgets;
}

// Handle real-time dashboard updates from SSE
function handleDashboardUpdate(data) {
  if (data.action === "set_layout") {
    // New tab created — reload tabs and switch to it
    if (data.tab_id) {
      activeTabId = data.tab_id;
    }
    loadDashboard();
    return;
  }

  if (data.action === "add" || data.action === "refresh") {
    // A widget was added or a tab was refreshed — reload
    loadDashboard();
    return;
  }

  const grid = document.getElementById("widget-grid");
  if (!grid) return;

  if (data.action === "remove") {
    const el = document.getElementById(`widget-${data.widget_id}`);
    if (el) el.remove();
    if (grid.children.length === 0) {
      grid.innerHTML = '<div class="widget-grid-empty">No widgets</div>';
    }
  } else if (data.action === "update") {
    const el = document.getElementById(`widget-${data.widget_id}`);
    if (el) {
      let config = data.config;
      try { config = typeof config === "string" ? JSON.parse(config) : config; } catch {}
      const widget = {
        id: data.widget_id,
        type: el.dataset.type || "chart",
        title: data.title || el.querySelector(".widget-header span")?.textContent || "",
        size: data.size || el.className.match(/widget-(quarter|half|full)/)?.[1] || "half",
        config: config || {},
      };
      const newEl = createWidgetElement(widget);
      el.replaceWith(newEl);
    }
  }
}

// Backward-compatible renderDashboard that uses widget grid
function renderDashboard(stats) {
  const widgets = generateDefaultWidgets(stats);
  renderWidgetGrid(widgets);
}

// --- Activity Feed ---

async function loadActivity() {
  if (activeTabId !== "project") return; // only show activity on project tab

  const grid = document.getElementById("widget-grid");
  if (!grid) return;

  try {
    const res = await fetch("/api/dashboard/activity");
    if (!res.ok) return;
    const data = await res.json();
    const activities = data.activities || [];
    if (!activities.length) return;

    const activityWidget = document.createElement("div");
    activityWidget.className = "widget widget-full";
    activityWidget.id = "widget-activity-feed";
    activityWidget.innerHTML = `
      <div class="widget-header"><span>Recent Activity</span></div>
      <div class="widget-body"></div>
    `;

    const body = activityWidget.querySelector(".widget-body");
    body.innerHTML = `
      <div class="activity-feed">
        ${activities.map((a) => {
          const timeAgo = formatTimeAgo(new Date(a.createdAt));
          const icon = a.type === "pr" ? prIcon(a.status) : commitIcon();
          const statusBadge = a.type === "pr" && a.status
            ? `<span class="activity-status activity-status-${a.status}">${a.status}</span>`
            : "";
          return `
            <div class="activity-item">
              <div class="activity-icon">${icon}</div>
              <div class="activity-content">
                <a href="${escapeHtml(a.url)}" target="_blank" rel="noopener" class="activity-title">${escapeHtml(a.title)}</a>
                <div class="activity-meta">
                  <span>${escapeHtml(a.author)}</span>
                  <span class="activity-repo">${escapeHtml(a.repo)}</span>
                  ${statusBadge}
                  <span class="activity-time">${timeAgo}</span>
                </div>
              </div>
            </div>
          `;
        }).join("")}
      </div>
    `;

    const existing = document.getElementById("widget-activity-feed");
    if (existing) existing.replaceWith(activityWidget);
    else grid.appendChild(activityWidget);
  } catch {
    // Silently fail
  }
}

function prIcon(status) {
  const color = status === "merged" ? "#00c853" : status === "open" ? "#e8912d" : "#ff3d3d";
  return `<svg width="14" height="14" viewBox="0 0 16 16" fill="${color}"><path d="M7.177 3.073L9.573.677A.25.25 0 0110 .854v4.792a.25.25 0 01-.427.177L7.177 3.427a.25.25 0 010-.354zM3.75 2.5a.75.75 0 100 1.5.75.75 0 000-1.5zm-2.25.75a2.25 2.25 0 113 2.122v5.256a2.251 2.251 0 11-1.5 0V5.372A2.25 2.25 0 011.5 3.25zM11 2.5h-1V4h1a1 1 0 011 1v5.628a2.251 2.251 0 101.5 0V5A2.5 2.5 0 0011 2.5zm1 10.25a.75.75 0 111.5 0 .75.75 0 01-1.5 0zM3.75 12a.75.75 0 100 1.5.75.75 0 000-1.5z"/></svg>`;
}

function commitIcon() {
  return `<svg width="14" height="14" viewBox="0 0 16 16" fill="#8b949e"><path d="M11.93 8.5a4.002 4.002 0 01-7.86 0H.75a.75.75 0 010-1.5h3.32a4.002 4.002 0 017.86 0h3.32a.75.75 0 010 1.5h-3.32zm-1.43-.75a2.5 2.5 0 10-5 0 2.5 2.5 0 005 0z"/></svg>`;
}

function formatTimeAgo(date) {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString();
}

// --- Session Metadata ---

function updateSessionMeta() {
  const msgCount = messagesEl.querySelectorAll(".message").length;
  document.getElementById("session-meta").textContent = `MSGS: ${msgCount}`;
}
