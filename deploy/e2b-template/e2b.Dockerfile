# Kai Agent E2B Template
# Pre-installs the agent and all dependencies so sandbox creation is fast.
# Build: e2b template build --name kai-agent
# This creates a custom E2B template that provisions in <1s.

FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl build-essential && \
    rm -rf /var/lib/apt/lists/*

# Node.js (for MCP tools that need npx)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /home/user/kai-agent

# Copy agent code
COPY . /home/user/kai-agent/

# Install Python deps
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir e2b httpx mcp>=1.26.0

# Initialize mini-swe-agent submodule
RUN cd /home/user/kai-agent && git init && \
    git submodule update --init mini-swe-agent 2>/dev/null || true

# Create config directory
RUN mkdir -p /home/user/.kai-agent

# Default config (JWT injected at runtime via env vars)
COPY deploy/e2b-template/default-config.yaml /home/user/.kai-agent/config.yaml

# Link skills
RUN ln -sf /home/user/kai-agent/skills /home/user/.kai-agent/skills

# Create sessions and memories directories
RUN mkdir -p /home/user/.kai-agent/sessions /home/user/.kai-agent/memories

# Set working directory for agent
WORKDIR /home/user
