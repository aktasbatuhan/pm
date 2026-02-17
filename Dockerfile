FROM oven/bun:1 AS base
WORKDIR /app

# Install dependencies
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile --production

# Copy source
COPY src/ ./src/
COPY tsconfig.json ./
COPY drizzle.config.ts ./

# Copy knowledge as seed (will be copied to DATA_DIR on first boot)
COPY knowledge/ ./knowledge-seed/

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
