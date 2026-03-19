#!/bin/bash
set -e

cd /app

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

# ── Start Control Panel in background (bind to all interfaces in Docker)
export PANEL_HOST=0.0.0.0
echo "[entrypoint] Starting Control Panel on :9090..."
python3 /app/control-panel/server.py &

# ── Start PyBridge ───────────────────────────────────────────────────
echo "[entrypoint] Starting PyBridge..."
cd /app/pybridge
exec python3 main.py
