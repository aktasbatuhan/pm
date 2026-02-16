import { Hono } from "hono";
import { serveStatic } from "hono/bun";
import { createRoutes } from "./routes.ts";
import { authMiddleware, createAuthRoutes } from "./auth.ts";
import { startJobLoop } from "../scheduler/loop.ts";

export function createServer() {
  const app = new Hono();

  // Auth middleware (skipped if AUTH_TOKEN not set)
  app.use("*", authMiddleware);

  // Auth routes (login endpoint + login page)
  createAuthRoutes(app);

  // API routes
  const api = createRoutes();
  app.route("/api", api);

  // Static files
  app.use("/*", serveStatic({ root: "./src/web/public" }));

  return app;
}

export function startServer(port: number = 3000) {
  const app = createServer();

  console.log(`\n  PM Agent Web UI`);
  console.log(`  http://localhost:${port}\n`);

  // Start background job loop
  startJobLoop();

  return Bun.serve({
    port,
    fetch: app.fetch,
    idleTimeout: 255,
  });
}
