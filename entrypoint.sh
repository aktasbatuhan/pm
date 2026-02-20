#!/bin/sh
# PM Agent entrypoint — seeds knowledge files on first boot

DATA_DIR="${DATA_DIR:-/data}"
KNOWLEDGE_DIR="$DATA_DIR/knowledge"
WORKSPACE_DIR="$DATA_DIR/workspace"

# Ensure data dir exists first
mkdir -p "$DATA_DIR"
mkdir -p "$WORKSPACE_DIR"

# Seed knowledge files from image if not already present
if [ ! -d "$KNOWLEDGE_DIR" ]; then
  echo "[init] Seeding knowledge files to $KNOWLEDGE_DIR..."
  cp -r /app/knowledge-seed "$KNOWLEDGE_DIR"
else
  echo "[init] Knowledge directory exists at $KNOWLEDGE_DIR"
fi

echo "[init] DATA_DIR=$DATA_DIR"
echo "[init] Starting PM Agent..."

exec bun run src/index.ts web
