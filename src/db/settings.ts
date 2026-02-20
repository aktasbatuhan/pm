import { getDb } from "./index.ts";
import { settings } from "./schema.ts";
import { eq } from "drizzle-orm";

/** Setting keys → env var fallbacks */
const ENV_FALLBACK: Record<string, string> = {
  "integration.exa_api_key": "EXA_API_KEY",
  "integration.granola_api_key": "GRANOLA_API_KEY",
  "integration.posthog_api_key": "POSTHOG_API_KEY",
  "integration.posthog_host": "POSTHOG_HOST",
  "integration.posthog_project_id": "POSTHOG_PROJECT_ID",
  "integration.slack_webhook_url": "SLACK_WEBHOOK_URL",
  "slack.allowed_users": "",
  "slack.allowed_channels": "",
};

/** All known setting keys */
export const SETTING_KEYS = Object.keys(ENV_FALLBACK);

/** Keys that contain sensitive values (masked in API responses) */
export const SENSITIVE_KEYS = [
  "integration.exa_api_key",
  "integration.granola_api_key",
  "integration.posthog_api_key",
  "integration.slack_webhook_url",
];

/** Get a setting. DB first, then env fallback, then null. */
export function getSetting(key: string): unknown | null {
  const db = getDb();
  const row = db.select().from(settings).where(eq(settings.key, key)).get();
  if (row) return row.value;

  const envKey = ENV_FALLBACK[key];
  if (envKey && process.env[envKey]) return process.env[envKey];

  return null;
}

/** Get a setting as a string. */
export function getSettingString(key: string, defaultValue: string = ""): string {
  const val = getSetting(key);
  if (val === null || val === undefined) return defaultValue;
  return String(val);
}

/** Get a setting as a string array. */
export function getSettingArray(key: string): string[] {
  const val = getSetting(key);
  if (Array.isArray(val)) return val;
  if (typeof val === "string" && val) return [val];
  return [];
}

/** Set a setting (upsert). */
export function setSetting(key: string, value: unknown): void {
  const db = getDb();
  const now = new Date();
  db.insert(settings)
    .values({ key, value: value as any, updatedAt: now })
    .onConflictDoUpdate({
      target: settings.key,
      set: { value: value as any, updatedAt: now },
    })
    .run();
}

/** Delete a setting (reverts to env fallback). */
export function deleteSetting(key: string): void {
  getDb().delete(settings).where(eq(settings.key, key)).run();
}

/** Get all settings as key-value map (env defaults + DB overrides). */
export function getAllSettings(): Record<string, unknown> {
  const db = getDb();
  const rows = db.select().from(settings).all();
  const result: Record<string, unknown> = {};

  // Populate from env fallbacks
  for (const [key, envVar] of Object.entries(ENV_FALLBACK)) {
    if (envVar && process.env[envVar]) {
      result[key] = process.env[envVar];
    }
  }

  // DB overrides
  for (const row of rows) {
    result[row.key] = row.value;
  }

  return result;
}

/** Mask an API key for display: show last 4 chars only. */
export function maskApiKey(value: string | null | undefined): string {
  if (!value || value.length < 4) return value ? "****" : "";
  return "****" + value.slice(-4);
}
