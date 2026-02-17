import { type Context, type Next } from "hono";
import { getCookie, setCookie } from "hono/cookie";

const SESSION_COOKIE = "pm_agent_session";
const SESSION_MAX_AGE = 7 * 24 * 60 * 60; // 7 days in seconds

// Simple in-memory session store (sufficient for single-instance)
const validSessions = new Set<string>();

function getAuthToken(): string | null {
  return process.env.AUTH_TOKEN || null;
}

/**
 * Auth middleware. If AUTH_TOKEN is not set, all requests are allowed (dev mode).
 * Otherwise, checks for:
 * 1. Valid session cookie
 * 2. Authorization: Bearer <token> header
 */
export async function authMiddleware(c: Context, next: Next) {
  const token = getAuthToken();

  // No AUTH_TOKEN configured — skip auth (dev/localhost mode)
  if (!token) {
    return next();
  }

  // Allow health check (needed for Railway/Docker health probes)
  if (c.req.path === "/api/health") {
    return next();
  }

  // Allow login endpoint
  if (c.req.path === "/api/auth/login" && c.req.method === "POST") {
    return next();
  }

  // Allow login page
  if (c.req.path === "/login") {
    return next();
  }

  // Check session cookie
  const sessionId = getCookie(c, SESSION_COOKIE);
  if (sessionId && validSessions.has(sessionId)) {
    return next();
  }

  // Check Bearer token
  const authHeader = c.req.header("Authorization");
  if (authHeader?.startsWith("Bearer ")) {
    const bearer = authHeader.slice(7);
    if (bearer === token) {
      return next();
    }
  }

  // Not authenticated — redirect to login or return 401
  if (c.req.path.startsWith("/api/")) {
    return c.json({ error: "Unauthorized" }, 401);
  }

  // Redirect HTML requests to login page
  return c.redirect("/login");
}

/**
 * Create auth routes (login endpoint).
 */
export function createAuthRoutes(app: any) {
  app.post("/api/auth/login", async (c: Context) => {
    const token = getAuthToken();
    if (!token) {
      return c.json({ success: true }); // No auth configured
    }

    const body = await c.req.json<{ token: string }>();
    if (body.token !== token) {
      return c.json({ error: "Invalid token" }, 401);
    }

    // Create session
    const sessionId = crypto.randomUUID();
    validSessions.add(sessionId);

    const isSecure = c.req.header("x-forwarded-proto") === "https";
    setCookie(c, SESSION_COOKIE, sessionId, {
      httpOnly: true,
      secure: isSecure,
      sameSite: "Lax",
      maxAge: SESSION_MAX_AGE,
      path: "/",
    });

    return c.json({ success: true });
  });

  // Serve login page
  app.get("/login", (c: Context) => {
    return c.html(LOGIN_HTML);
  });
}

const LOGIN_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PM Agent — Login</title>
  <style>
    :root {
      --bg-primary: #0d1117;
      --bg-secondary: #161b22;
      --bg-tertiary: #1c2128;
      --border: #30363d;
      --text-primary: #e6edf3;
      --text-secondary: #8b949e;
      --text-muted: #484f58;
      --accent: #58a6ff;
      --accent-dim: #1f6feb;
      --red: #f85149;
      --font-mono: "SF Mono", "Fira Code", Consolas, monospace;
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, sans-serif;
      --radius: 6px;
    }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--bg-primary);
      font-family: var(--font-sans);
      color: var(--text-primary);
    }
    .login-card {
      width: 360px;
      background: var(--bg-secondary);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 32px;
    }
    h2 { font-size: 18px; margin-bottom: 4px; }
    .subtitle { font-size: 13px; color: var(--text-secondary); margin-bottom: 24px; }
    input {
      width: 100%;
      background: var(--bg-tertiary);
      border: 1px solid var(--border);
      color: var(--text-primary);
      font-family: var(--font-mono);
      font-size: 13px;
      padding: 10px 14px;
      border-radius: var(--radius);
      outline: none;
      margin-bottom: 12px;
    }
    input:focus { border-color: var(--accent-dim); }
    input::placeholder { color: var(--text-muted); }
    button {
      width: 100%;
      padding: 10px;
      background: var(--accent-dim);
      border: none;
      border-radius: var(--radius);
      color: var(--text-primary);
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
    }
    button:hover { background: var(--accent); }
    .error { color: var(--red); font-size: 12px; font-family: var(--font-mono); margin-bottom: 12px; min-height: 16px; }
  </style>
</head>
<body>
  <div class="login-card">
    <h2>PM Agent</h2>
    <p class="subtitle">Enter your access token to continue.</p>
    <input type="password" id="token" placeholder="Access token..." autocomplete="off" />
    <div class="error" id="error"></div>
    <button id="login-btn">Login</button>
  </div>
  <script>
    const tokenEl = document.getElementById("token");
    const errorEl = document.getElementById("error");
    document.getElementById("login-btn").addEventListener("click", login);
    tokenEl.addEventListener("keydown", (e) => { if (e.key === "Enter") login(); });

    async function login() {
      const token = tokenEl.value.trim();
      if (!token) { errorEl.textContent = "Enter a token"; return; }
      errorEl.textContent = "";
      try {
        const res = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        });
        if (res.ok) {
          window.location.href = "/";
        } else {
          errorEl.textContent = "Invalid token";
        }
      } catch (err) {
        errorEl.textContent = "Connection error";
      }
    }
  </script>
</body>
</html>`;
