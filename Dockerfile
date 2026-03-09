FROM oven/bun:1 AS base
WORKDIR /app

# Install git and gh CLI
RUN apt-get update && \
    apt-get install -y git curl && \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg 2>/dev/null && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && \
    apt-get install -y gh && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile --production

# Build frontend
COPY frontend/package.json frontend/bun.lock ./frontend/
RUN cd frontend && bun install --frozen-lockfile
COPY frontend/ ./frontend/
RUN cd frontend && bun run build

# Copy source
COPY src/ ./src/
COPY tsconfig.json ./
COPY drizzle.config.ts ./

# Copy knowledge as seed (will be copied to DATA_DIR on first boot)
COPY knowledge/ ./knowledge-seed/

# Copy skills (updated on every deploy — they're app code, not user data)
COPY skills/ ./skills/

# Copy entrypoint
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Default data directory (overridden by volume mount)
ENV DATA_DIR=/data

# Health check (use bun instead of curl which may not be installed)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD bun -e "const r = await fetch('http://localhost:' + (process.env.PORT || 3000) + '/api/health'); if (!r.ok) process.exit(1);" || exit 1

EXPOSE 3000

ENTRYPOINT ["./entrypoint.sh"]
