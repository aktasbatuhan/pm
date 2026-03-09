import { Hono } from "hono";
import { serveStatic } from "hono/bun";
import { createRoutes } from "./routes.ts";
import { authMiddleware, createAuthRoutes } from "./auth.ts";
import { startJobLoop } from "../scheduler/loop.ts";
import { startTabRefreshLoop } from "../scheduler/tab-refresh.ts";
import { startSlackBot } from "../slack/bot.ts";

export function createServer() {
  const app = new Hono();

  // Security headers for HTML responses
  app.use("*", async (c, next) => {
    await next();
    const ct = c.res.headers.get("content-type") || "";
    if (ct.includes("text/html")) {
      c.header("X-Frame-Options", "DENY");
      c.header("Content-Security-Policy", "frame-ancestors 'none'");
    }
  });

  // Auth middleware (skipped if AUTH_TOKEN not set)
  app.use("*", authMiddleware);

  // Auth routes (login endpoint + login page)
  createAuthRoutes(app);

  // API routes
  const api = createRoutes();
  app.route("/api", api);

  // Static files — serve React SPA from frontend/dist, fall back to old public
  app.use("/*", serveStatic({ root: "./frontend/dist" }));
  app.use("/*", serveStatic({ root: "./src/web/public" }));

  // SPA fallback — serve index.html for client-side routes
  app.get("/*", async (c) => {
    const file = Bun.file("./frontend/dist/index.html");
    if (await file.exists()) {
      return c.html(await file.text());
    }
    return c.text("Not found", 404);
  });

  return app;
}

export function startServer(port: number = 3000) {
  const app = createServer();

  console.log(`\n  PM Agent Web UI`);
  console.log(`  http://localhost:${port}\n`);

  // Start background loops
  startJobLoop();
  startTabRefreshLoop();

  // Start Slack bot if configured
  startSlackBot();

  return Bun.serve({
    port,
    fetch: app.fetch,
    idleTimeout: 255,
  });
}
