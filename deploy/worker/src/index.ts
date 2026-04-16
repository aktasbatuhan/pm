/**
 * Kai Agent Gateway - Cloudflare Worker
 */

export interface Env {
  E2B_API_KEY: string;
  E2B_SANDBOX_ID: string;
  E2B_SANDBOX_URL: string;
  SLACK_SIGNING_SECRET: string;
}

async function verifySlackSignature(
  request: Request, body: string, signingSecret: string,
): Promise<boolean> {
  const timestamp = request.headers.get("x-slack-request-timestamp");
  const signature = request.headers.get("x-slack-signature");
  if (!timestamp || !signature) return false;
  if (Math.abs(Math.floor(Date.now() / 1000) - parseInt(timestamp)) > 300) return false;
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(signingSecret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`v0:${timestamp}:${body}`));
  const computed = `v0=${Array.from(new Uint8Array(sig)).map((b) => b.toString(16).padStart(2, "0")).join("")}`;
  return computed === signature;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return Response.json({ status: "ok", service: "kai-agent-gateway" });
    }

    if (url.pathname === "/slack/events" && request.method === "POST") {
      const body = await request.text();

      let event: any;
      try {
        event = JSON.parse(body);
      } catch {
        console.error("Failed to parse JSON body");
        return new Response("Bad request", { status: 400 });
      }

      if (event.type === "url_verification") {
        return Response.json({ challenge: event.challenge });
      }

      // Verify signature
      const sigValid = await verifySlackSignature(request, body, env.SLACK_SIGNING_SECRET);
      console.log("[1] Signature valid:", sigValid);
      if (!sigValid) {
        return new Response("Invalid signature", { status: 401 });
      }

      const msg = event.event;
      if (!msg) {
        console.log("[2] No event field");
        return new Response("ok");
      }

      console.log("[2] Event type:", msg.type, "bot_id:", msg.bot_id, "text:", (msg.text || "").substring(0, 60));

      // Process ALL message types that mention the bot (not just app_mention)
      const botMention = `<@${msg.user === undefined ? "" : ""}`;
      const text = msg.text || "";

      // Skip bot's own messages
      if (msg.bot_id || msg.subtype === "bot_message") {
        console.log("[3] Skipping bot message");
        return new Response("ok");
      }

      // For app_mention, always process. For message.channels, check if it mentions the bot.
      if (msg.type !== "app_mention") {
        console.log("[3] Not app_mention, skipping:", msg.type);
        return new Response("ok");
      }

      const message = text.replace(/<@[A-Z0-9]+>\s*/g, "").trim();
      console.log("[4] Clean message:", message);
      if (!message) {
        console.log("[4] Empty message after stripping mention");
        return new Response("ok");
      }

      // Resume sandbox
      console.log("[5] Resuming sandbox:", env.E2B_SANDBOX_ID);
      try {
        const resumeRes = await fetch(`https://api.e2b.dev/sandboxes/${env.E2B_SANDBOX_ID}/resume`, {
          method: "POST",
          headers: { "X-API-Key": env.E2B_API_KEY, "Content-Type": "application/json" },
          body: JSON.stringify({ timeout: 3600 }),
        });
        console.log("[5] Resume status:", resumeRes.status);
      } catch (err) {
        console.error("[5] Resume failed:", err);
      }

      // Dispatch
      const longRunning = /evolve|evolution|scan|overnight|monitor|keep.*posted/i.test(message);
      console.log("[6] Dispatching to:", env.E2B_SANDBOX_URL);
      try {
        const dispatchRes = await fetch(`${env.E2B_SANDBOX_URL}/dispatch`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message,
            channel: msg.channel,
            threadTs: msg.thread_ts || msg.ts,
            longRunning,
          }),
        });
        const dispatchBody = await dispatchRes.text();
        console.log("[6] Dispatch status:", dispatchRes.status, "body:", dispatchBody);
      } catch (err) {
        console.error("[6] Dispatch failed:", err);
      }

      console.log("[7] Done");
      return new Response("ok");
    }

    return new Response("Kai Agent Gateway", { status: 200 });
  },
};
