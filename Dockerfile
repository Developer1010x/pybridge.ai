# ─────────────────────────────────────────────────────────────────────
#  pybridge.ai — multi-platform Docker image
#  Python 3.11 + Node.js 20 + Chromium (for Playwright browser plugin)
# ─────────────────────────────────────────────────────────────────────

FROM python:3.11-slim AS base

# ── System deps ──────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        git \
        ffmpeg \
        sqlite3 \
        gnupg \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Node.js 20 ──────────────────────────────────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ────────────────────────────────────────────────
WORKDIR /app

# ── Python deps (cached layer) ──────────────────────────────────────
COPY pybridge/requirements.txt /app/pybridge/requirements.txt
RUN pip install --no-cache-dir -r /app/pybridge/requirements.txt

# ── Install Playwright Chromium ──────────────────────────────────────
RUN playwright install --with-deps chromium

# ── WhatsApp bridge Node deps (cached layer) ─────────────────────────
COPY pybridge/whatsapp_bridge/package.json pybridge/whatsapp_bridge/package-lock.json* /app/pybridge/whatsapp_bridge/
RUN cd /app/pybridge/whatsapp_bridge && npm install --production

# ── Copy application code ────────────────────────────────────────────
COPY pybridge/ /app/pybridge/
COPY control-panel/ /app/control-panel/

# ── Directories for persistent data ─────────────────────────────────
RUN mkdir -p /data/sessions /data/whatsapp-auth

# ── Default env vars (overridden by .env or docker-compose) ──────────
ENV PYTHONUNBUFFERED=1
ENV PYBRIDGE_SESSIONS_DIR=/data/sessions
ENV WHATSAPP_AUTH_DIR=/data/whatsapp-auth

# ── Ports ────────────────────────────────────────────────────────────
#  9090  — Control Panel web UI
#  8765  — Screen live-stream (optional)
#  8766  — WhatsApp bridge (internal)
EXPOSE 9090 8765 8766

# ── Healthcheck ──────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9090/api/health')" || exit 1

# ── Entrypoint ───────────────────────────────────────────────────────
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
