#!/bin/bash
set -e

cd /app

# ── Warn about the classic bind-mount trap ───────────────────────────
# If pybridge/.env does not exist on the host, Docker creates a *directory*
# at the mount point. PyBridge ignores it, but the secrets you expected to
# be there will silently not be loaded.
if [ -d /app/pybridge/.env ]; then
    echo "[entrypoint] WARNING: /app/pybridge/.env is a directory."
    echo "[entrypoint]          Run 'cp pybridge/.env.example pybridge/.env' on the"
    echo "[entrypoint]          host and recreate the container, or pass the keys via"
    echo "[entrypoint]          'environment:' in docker-compose.yml."
fi

# ── Override sessions dir if env var set ─────────────────────────────
if [ -n "$PYBRIDGE_SESSIONS_DIR" ]; then
    # Patch config.json sessions_dir
    python3 -c "
import json, os
cfg_path = '/app/pybridge/config.json'
with open(cfg_path) as f:
    cfg = json.load(f)
cfg['sessions_dir'] = os.environ.get('PYBRIDGE_SESSIONS_DIR', '~/.pybridge/sessions')
with open(cfg_path, 'w') as f:
    json.dump(cfg, f, indent=2)
"
fi

# ── Start Control Panel in background ────────────────────────────────
# Inside a container the panel has to bind 0.0.0.0 for the published port to
# reach it. That is only safe because the panel requires a token (set
# PANEL_TOKEN to pin it) and compose publishes the port on 127.0.0.1 only.
export PANEL_HOST="${PANEL_HOST:-0.0.0.0}"
echo "[entrypoint] Starting Control Panel on ${PANEL_HOST}:9090..."
python3 /app/control-panel/server.py &

# ── Start PyBridge ───────────────────────────────────────────────────
echo "[entrypoint] Starting PyBridge..."
cd /app/pybridge
exec python3 main.py "$@"
