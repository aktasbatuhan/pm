# Kai Agent E2B Template
# Build from repo root: python e2b_build.py
# Chat server starts on port 8080 via template start_cmd.

FROM python:3.12-bookworm

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl build-essential \
    && rm -rf /var/lib/apt/lists/*

# Node.js 20 (for MCP tools that need npx)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install uv (match executor pattern)
RUN curl -LsSf https://astral.sh/uv/0.9.11/install.sh | sh
RUN cp /root/.local/bin/uv /usr/local/bin/uv && cp /root/.local/bin/uvx /usr/local/bin/uvx
ENV PATH="/root/.local/bin:${PATH}"

# Copy agent code and install deps
WORKDIR /home/user/kai-agent
COPY . .
RUN uv sync --locked --all-extras

# Create config directory
RUN mkdir -p /home/user/.kai-agent/sessions /home/user/.kai-agent/memories

# Default config (JWT and secrets injected at runtime via env vars)
COPY deploy/e2b-template/default-config.yaml /home/user/.kai-agent/config.yaml

# Link skills
RUN ln -sf /home/user/kai-agent/skills /home/user/.kai-agent/skills

# Chat server (HTTP endpoint for frontend + Slack listener)
COPY deploy/e2b-template/kai_chat_server.py /home/user/kai_chat_server.py

# WORKDIR stays at /home/user/kai-agent so uv can find pyproject.toml + .venv
# (template's set_workdir confirms this)
