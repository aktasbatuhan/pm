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
  console.log("📊 [viz] Creating chart container");
  console.log("📊 [viz] Container element:", container, {
    tagName: container?.tagName,
    className: container?.className,
    id: container?.id,
    parentNode: container?.parentNode,
    isConnected: container?.isConnected
  });

  const wrapper = document.createElement("div");
  wrapper.className = "chart-container";
  wrapper.style.backgroundColor = "var(--bg-tertiary)";
  wrapper.style.border = "2px solid var(--accent)"; // Make it obvious for debugging
  wrapper.style.height = "300px";
  wrapper.style.margin = "10px 0";

  if (input.title) {
    const title = document.createElement("div");
    title.className = "chart-title";
    title.textContent = input.title;
    wrapper.appendChild(title);
    console.log("📊 [viz] Added chart title:", input.title);
  }

  const canvas = document.createElement("canvas");
  canvas.style.width = "100%";
  canvas.style.height = "280px";
  canvas.style.display = "block";
  wrapper.appendChild(canvas);
  container.appendChild(wrapper);

  console.log("📊 [viz] About to append wrapper to container");
  console.log("📊 [viz] Wrapper before append:", wrapper, "Parent:", wrapper.parentNode);

  try {
    container.appendChild(wrapper);
    console.log("📊 [viz] ✅ Wrapper appended successfully");
    console.log("📊 [viz] Wrapper after append:", wrapper, "Parent:", wrapper.parentNode);
    console.log("📊 [viz] Container now has children:", container.children.length);
    console.log("📊 [viz] Chart container added to DOM", {
      wrapper: wrapper,
      canvas: canvas,
      container: container,
      containerHeight: wrapper.offsetHeight,
      canvasSize: { width: canvas.width, height: canvas.height }
    });

    // Force a repaint
    wrapper.style.display = 'none';
    wrapper.offsetHeight; // trigger reflow
    wrapper.style.display = 'block';

  } catch (error) {
    console.error("❌ [viz] Failed to append wrapper to container:", error);
    console.error("❌ [viz] Container:", container);
    console.error("❌ [viz] Wrapper:", wrapper);
  }

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

  const config = {
    type: input.type,
    data: { labels: input.data.labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      color: themeDefaults.color,
      borderColor: themeDefaults.borderColor,
      plugins: themeDefaults.plugins,
      ...(noAxes ? {} : { scales: themeDefaults.scales }),
      ...(input.options || {}),
    },
  };

  try {
    const chart = new Chart(canvas, config);
    console.log("📊 [viz] Chart.js instance created:", chart);
  } catch (error) {
    console.error("❌ [viz] Chart.js error:", error);
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
const setupState = { token: "", username: "", org: "", selectedProject: null };

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

// Step 3: Complete
document.getElementById("btn-complete-setup").addEventListener("click", async () => {
  if (!setupState.selectedProject) {
    alert("Select a project first");
    return;
  }

  const genKnowledge = document.getElementById("setup-gen-knowledge").checked;
  setSetupLoading(true, genKnowledge ? "Generating knowledge files..." : "Saving configuration...");

  try {
    const res = await fetch("/api/setup/complete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token: setupState.token,
        org: setupState.org,
        projectNumber: setupState.selectedProject,
        generateKnowledgeFiles: genKnowledge,
      }),
    });
    const data = await res.json();
    setSetupLoading(false);

    const logsEl = document.getElementById("setup-logs");
    logsEl.innerHTML = (data.logs || [])
      .map((l) => {
        const cls = l.includes("Skipped") ? "log-warn" : "log-ok";
        return `<div class="${cls}">${escapeHtml(l)}</div>`;
      })
      .join("");

    goToSetupStep(4);
  } catch (err) {
    setSetupLoading(false);
    alert(`Setup failed: ${err.message}`);
  }
});

// Step 4: Start
document.getElementById("btn-start-chat").addEventListener("click", () => {
  hideSetup();
  hideOnboardingBanner();
  sessionStorage.removeItem("onboarding-dismissed");
  setTimeout(() => checkKnowledgeOnboarding(), 1000);
});

// Reconfigure button — reset wizard and show it
document.getElementById("reconfigure-btn").addEventListener("click", () => {
  setupState.token = "";
  setupState.username = "";
  setupState.org = "";
  setupState.selectedProject = null;
  document.getElementById("setup-token").value = "";
  document.getElementById("token-status").textContent = "";
  document.getElementById("token-status").className = "step-status";
  goToSetupStep(1);
  showSetup();
});

// --- Main App ---

const SLASH_COMMANDS = {
  "/standup": "Analyze the current sprint and give me a daily standup report. Focus on: what's in progress, what's blocked, what was completed recently, and any risks.",
  "/analyze": "Deep analysis of the current sprint: health, risks, blockers, progress, team workload, and actionable recommendations.",
  "/estimate": "Estimate effort for the specified issue using the Fibonacci scale (1, 2, 3, 5, 8, 13). Provide reasoning, breakdown, assumptions, and risks.",
};

let currentSessionId = null;
let isStreaming = false;
let totalCost = 0;

// DOM elements
const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("message-input");
const sendBtn = document.getElementById("send-btn");
const sessionsListEl = document.getElementById("sessions-list");
const newSessionBtn = document.getElementById("new-session");
const sessionNameEl = document.getElementById("session-name");
const costDisplayEl = document.getElementById("cost-display");

// Initialize — check setup status + knowledge onboarding
(async () => {
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
})();

// Event listeners
inputEl.addEventListener("input", () => {
  sendBtn.disabled = !inputEl.value.trim() || isStreaming;
  autoResize(inputEl);
});

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    if (!isStreaming && inputEl.value.trim()) sendMessage();
  }
});

sendBtn.addEventListener("click", sendMessage);

newSessionBtn.addEventListener("click", () => {
  currentSessionId = null;
  sessionNameEl.textContent = "New Conversation";
  messagesEl.innerHTML = getWelcomeHTML();
  attachQuickActions();
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
          sessionNameEl.textContent = "New Conversation";
          messagesEl.innerHTML = getWelcomeHTML();
          attachQuickActions();
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
  if (!text || isStreaming) return;

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

  isStreaming = true;
  let fullText = "";

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, sessionId: currentSessionId }),
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
              assistantDiv.innerHTML = renderMarkdown(fullText);
              scrollToBottom();
            }
          } else if (eventType === "visualization") {
            console.log("📊 [viz] Received visualization event:", data);
            thinkingDiv.style.display = "none";
            assistantDiv.style.display = "";
            if (data.tool === "render_chart") {
              try {
                console.log("📊 [viz] Parsing chart config:", (data.input.config || "").substring(0, 200) + "...");
                const chartConfig = JSON.parse(data.input.config);
                console.log("📊 [viz] Parsed chart config:", chartConfig);
                renderChartElement(assistantDiv, chartConfig);
                console.log("📊 [viz] Chart rendered successfully");
              } catch (e) {
                console.error("❌ [viz] Failed to parse chart config:", e, data.input.config);
              }
            } else if (data.tool === "render_diagram") {
              console.log("📊 [viz] Rendering diagram");
              renderMermaidElement(assistantDiv, data.input);
            }
            scrollToBottom();
          } else if (eventType === "tool") {
            const toolEl = document.createElement("div");
            toolEl.className = "tool-indicator";
            toolEl.innerHTML = `<span class="spinner"></span> ${data.tool}`;
            assistantDiv.appendChild(toolEl);
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
  sendBtn.disabled = !inputEl.value.trim();
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
  div.innerHTML = renderMarkdown(text);
  messagesEl.appendChild(div);
  scrollToBottom();
}

function renderMarkdown(text) {
  try {
    return marked.parse(text, { breaks: true, gfm: true });
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
  setupState.token = "";
  setupState.username = "";
  setupState.org = "";
  setupState.selectedProject = null;
  document.getElementById("setup-token").value = "";
  document.getElementById("token-status").textContent = "";
  document.getElementById("token-status").className = "step-status";
  goToSetupStep(1);
  showSetup();
});

document.getElementById("banner-dismiss-btn").addEventListener("click", () => {
  hideOnboardingBanner();
  sessionStorage.setItem("onboarding-dismissed", "true");
});

// --- Session Metadata ---

function updateSessionMeta() {
  const msgCount = messagesEl.querySelectorAll(".message").length;
  document.getElementById("session-meta").textContent = `MSGS: ${msgCount}`;
}
