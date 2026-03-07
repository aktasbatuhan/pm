import * as path from "path";

/**
 * Central path resolution for all persistent data.
 *
 * DATA_DIR env var controls where the DB and knowledge files live.
 * - Local dev: defaults to project root (.)
 * - Railway/Docker: set to /data (mounted volume)
 */
const DATA_DIR = process.env.DATA_DIR || process.cwd();

export const DB_PATH = path.join(DATA_DIR, "pm-agent.db");
export const KNOWLEDGE_DIR = path.join(DATA_DIR, "knowledge");
export const MEMORY_DIR = path.join(DATA_DIR, "memory");
