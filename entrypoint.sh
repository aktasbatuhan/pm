#!/bin/sh
# PM Agent entrypoint — seeds data files on first boot, preserves on updates

DATA_DIR="${DATA_DIR:-/data}"
KNOWLEDGE_DIR="$DATA_DIR/knowledge"
MEMORY_DIR="$DATA_DIR/memory"
WORKSPACE_DIR="$DATA_DIR/workspace"

# Ensure persistent directories exist
mkdir -p "$DATA_DIR" "$WORKSPACE_DIR" "$MEMORY_DIR"

# Seed knowledge files from image if not already present
if [ ! -d "$KNOWLEDGE_DIR" ]; then
  echo "[init] Seeding knowledge files to $KNOWLEDGE_DIR..."
  cp -r /app/knowledge-seed "$KNOWLEDGE_DIR"
else
  echo "[init] Knowledge directory exists at $KNOWLEDGE_DIR — preserving user data"
fi

# Always update skills from the image (they're part of the app, not user data)
if [ -d /app/skills ]; then
  mkdir -p "$DATA_DIR/skills"
  cp -r /app/skills/* "$DATA_DIR/skills/" 2>/dev/null || true
  echo "[init] Skills updated from image"
fi

# Load persistent .env if it exists (user reconfiguration survives redeploys)
if [ -f "$DATA_DIR/.env" ]; then
  echo "[init] Loading persistent .env from $DATA_DIR/.env"
  set -a
  . "$DATA_DIR/.env"
  set +a
fi

echo "[init] DATA_DIR=$DATA_DIR"
echo "[init] DB: $DATA_DIR/pm-agent.db"
echo "[init] Starting PM Agent..."

exec bun run src/index.ts web
