import { type Context, type Next } from "hono";
import { getCookie, setCookie } from "hono/cookie";
import { getDb, newId } from "../db/index.ts";
import { users, invites } from "../db/schema.ts";
import { eq } from "drizzle-orm";

const SESSION_COOKIE = "pm_agent_session";
const SESSION_MAX_AGE = 7 * 24 * 60 * 60; // 7 days

// In-memory session store: sessionId → userId
const validSessions = new Map<string, string>();

function getAuthToken(): string | null {
  return process.env.AUTH_TOKEN || null;
}

function findUserByToken(token: string) {
  return getDb().select().from(users).where(eq(users.token, token)).get();
}

function createSession(c: Context, userId: string) {
  const sessionId = crypto.randomUUID();
  validSessions.set(sessionId, userId);

  const isSecure = c.req.header("x-forwarded-proto") === "https";
  setCookie(c, SESSION_COOKIE, sessionId, {
    httpOnly: true,
    secure: isSecure,
    sameSite: "Lax",
    maxAge: SESSION_MAX_AGE,
    path: "/",
  });

  return sessionId;
}

/**
 * Auth middleware. If AUTH_TOKEN is not set, all requests are allowed (dev mode).
 * Otherwise, checks session cookie or Bearer token, attaches userId to context.
 */
export async function authMiddleware(c: Context, next: Next) {
  const token = getAuthToken();

  // No AUTH_TOKEN configured — skip auth (dev/localhost mode)
  if (!token) {
    return next();
  }

  // Allow public endpoints
  if (c.req.path === "/api/health") return next();
  if (c.req.path === "/api/auth/login" && c.req.method === "POST") return next();
  if (c.req.path === "/login") return next();
  if (c.req.path.startsWith("/join/")) return next();
  if (c.req.path === "/api/auth/join" && c.req.method === "POST") return next();

  // Check session cookie
  const sessionId = getCookie(c, SESSION_COOKIE);
  if (sessionId && validSessions.has(sessionId)) {
    c.set("userId", validSessions.get(sessionId)!);
    return next();
  }

  // Check Bearer token
  const authHeader = c.req.header("Authorization");
  if (authHeader?.startsWith("Bearer ")) {
    const bearer = authHeader.slice(7);
    const user = findUserByToken(bearer);
    if (user) {
      c.set("userId", user.id);
      return next();
    }
  }

  // Not authenticated
  if (c.req.path.startsWith("/api/")) {
    return c.json({ error: "Unauthorized" }, 401);
  }

  return c.redirect("/login");
}

/**
 * Create auth routes: login, /me, join flow.
 */
export function createAuthRoutes(app: any) {
  // Login with token
  app.post("/api/auth/login", async (c: Context) => {
    const token = getAuthToken();
    if (!token) return c.json({ success: true });

    const body = await c.req.json<{ token: string }>();
    const user = findUserByToken(body.token);
    if (!user) return c.json({ error: "Invalid token" }, 401);

    createSession(c, user.id);
    return c.json({ success: true });
  });

  // Current user info
  app.get("/api/auth/me", (c: Context) => {
    const userId = c.get("userId");
    if (!userId) return c.json({ user: null });

    const user = getDb().select().from(users).where(eq(users.id, userId)).get();
    if (!user) return c.json({ user: null });

    return c.json({
      user: { id: user.id, name: user.name, role: user.role },
    });
  });

  // Serve login page
  app.get("/login", (c: Context) => {
    return c.html(LOGIN_HTML);
  });

  // Serve join page
  app.get("/join/:token", (c: Context) => {
    return c.html(JOIN_HTML);
  });

  // Handle join
  app.post("/api/auth/join", async (c: Context) => {
    const body = await c.req.json<{ token: string; name: string }>();
    const db = getDb();

    const invite = db.select().from(invites)
      .where(eq(invites.token, body.token))
      .get();

    if (!invite || invite.usedBy) {
      return c.json({ error: "Invalid or used invite" }, 400);
    }

    const name = (body.name || "").trim();
    if (!name) return c.json({ error: "Name is required" }, 400);

    // Create user with a unique login token
    const userId = newId();
    const userToken = crypto.randomUUID();
    db.insert(users).values({
      id: userId,
      name,
      role: "member",
      token: userToken,
      createdAt: new Date(),
    }).run();

    // Mark invite as used
    db.update(invites)
      .set({ usedBy: userId })
      .where(eq(invites.id, invite.id))
      .run();

    createSession(c, userId);
    return c.json({ success: true });
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
      --bg-primary: #050a0f;
      --bg-secondary: #0a0e13;
      --bg-tertiary: #111519;
      --border: #1e2328;
      --text-primary: #e6edf3;
      --text-secondary: #8b949e;
      --text-muted: #484f58;
      --accent: #e8912d;
      --accent-dim: #b36d1a;
      --red: #ff3d3d;
      --font-mono: "SF Mono", "Fira Code", "JetBrains Mono", Consolas, monospace;
      --radius: 1px;
    }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--bg-primary);
      font-family: var(--font-mono);
      font-size: 12px;
      color: var(--text-primary);
    }
    .login-card {
      width: 340px;
      background: var(--bg-secondary);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 24px;
    }
    h2 { font-size: 14px; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.05em; }
    .subtitle { font-size: 11px; color: var(--text-secondary); margin-bottom: 20px; }
    input {
      width: 100%;
      background: var(--bg-tertiary);
      border: 1px solid var(--border);
      color: var(--text-primary);
      font-family: var(--font-mono);
      font-size: 11px;
      padding: 8px 10px;
      border-radius: var(--radius);
      outline: none;
      margin-bottom: 10px;
    }
    input:focus { border-color: var(--accent-dim); }
    input::placeholder { color: var(--text-muted); }
    button {
      width: 100%;
      padding: 8px;
      background: var(--accent-dim);
      border: none;
      border-radius: var(--radius);
      color: var(--text-primary);
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 500;
      cursor: pointer;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }
    button:hover { background: var(--accent); }
    .error { color: var(--red); font-size: 10px; font-family: var(--font-mono); margin-bottom: 10px; min-height: 14px; }
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

const JOIN_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PM Agent — Join Team</title>
  <style>
    :root {
      --bg-primary: #050a0f;
      --bg-secondary: #0a0e13;
      --bg-tertiary: #111519;
      --border: #1e2328;
      --text-primary: #e6edf3;
      --text-secondary: #8b949e;
      --text-muted: #484f58;
      --accent: #e8912d;
      --accent-dim: #b36d1a;
      --red: #ff3d3d;
      --font-mono: "SF Mono", "Fira Code", "JetBrains Mono", Consolas, monospace;
      --radius: 1px;
    }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--bg-primary);
      font-family: var(--font-mono);
      font-size: 12px;
      color: var(--text-primary);
    }
    .join-card {
      width: 340px;
      background: var(--bg-secondary);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 24px;
    }
    h2 { font-size: 14px; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.05em; }
    .subtitle { font-size: 11px; color: var(--text-secondary); margin-bottom: 20px; }
    input {
      width: 100%;
      background: var(--bg-tertiary);
      border: 1px solid var(--border);
      color: var(--text-primary);
      font-family: var(--font-mono);
      font-size: 11px;
      padding: 8px 10px;
      border-radius: var(--radius);
      outline: none;
      margin-bottom: 10px;
    }
    input:focus { border-color: var(--accent-dim); }
    input::placeholder { color: var(--text-muted); }
    button {
      width: 100%;
      padding: 8px;
      background: var(--accent-dim);
      border: none;
      border-radius: var(--radius);
      color: var(--text-primary);
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 500;
      cursor: pointer;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }
    button:hover { background: var(--accent); }
    .error { color: var(--red); font-size: 10px; font-family: var(--font-mono); margin-bottom: 10px; min-height: 14px; }
  </style>
</head>
<body>
  <div class="join-card">
    <h2>Join Team</h2>
    <p class="subtitle">Enter your name to join PM Agent.</p>
    <input type="text" id="name" placeholder="Your name..." autocomplete="off" />
    <div class="error" id="error"></div>
    <button id="join-btn">Join</button>
  </div>
  <script>
    const nameEl = document.getElementById("name");
    const errorEl = document.getElementById("error");
    const token = window.location.pathname.split("/join/")[1];

    document.getElementById("join-btn").addEventListener("click", join);
    nameEl.addEventListener("keydown", (e) => { if (e.key === "Enter") join(); });

    async function join() {
      const name = nameEl.value.trim();
      if (!name) { errorEl.textContent = "Enter your name"; return; }
      if (!token) { errorEl.textContent = "Invalid invite link"; return; }
      errorEl.textContent = "";
      try {
        const res = await fetch("/api/auth/join", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token, name }),
        });
        if (res.ok) {
          window.location.href = "/";
        } else {
          const data = await res.json();
          errorEl.textContent = data.error || "Failed to join";
        }
      } catch (err) {
        errorEl.textContent = "Connection error";
      }
    }
  </script>
</body>
</html>`;
