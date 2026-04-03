# ── Stage 1: build ────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install Node.js 22 (required by Copilot CLI)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install GitHub Copilot CLI globally
RUN npm install -g @github/copilot

# Install Python dependencies
COPY pyproject.toml .
COPY server/ ./server/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install Node.js 22 runtime (needed to run Copilot CLI)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy Copilot CLI from builder
COPY --from=builder /usr/lib/node_modules /usr/lib/node_modules
COPY --from=builder /usr/bin/copilot /usr/bin/copilot

# Copy installed Python packages and entry-point scripts
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/copilot-sdk-openai-proxy /usr/local/bin/copilot-sdk-openai-proxy

# Copy application source
COPY server/ ./server/

EXPOSE 8081

# Authentication: pass COPILOT_GITHUB_TOKEN (or GH_TOKEN / GITHUB_TOKEN) at runtime

# Allow configuring the listening port at runtime (default: 8081)
ENV PORT="8081"

# Use a shell entrypoint so we can expand the PORT env var into the command line
ENTRYPOINT ["/bin/sh", "-c", "exec copilot-sdk-openai-proxy --host 0.0.0.0 --port ${PORT}"]
