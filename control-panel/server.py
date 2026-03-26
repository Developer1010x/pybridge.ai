#!/usr/bin/env python3
"""
pybridge.ai Control Panel — lightweight web GUI for managing PyBridge.

Run:  python3 control-panel/server.py
Open:  http://localhost:9090
"""

import json
import os
import subprocess
import sys
import signal
import shutil
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYBRIDGE_DIR = ROOT / "pybridge"
PYBRIDGE_CONFIG = PYBRIDGE_DIR / "config.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"

HOST = os.environ.get("PANEL_HOST", "127.0.0.1")
PORT = int(os.environ.get("PANEL_PORT", "9090"))


# ─── helpers ─────────────────────────────────────────────────────────

def read_config():
    """Read the PyBridge config.json (redacting secrets)."""
    if not PYBRIDGE_CONFIG.exists():
        return {}
    with open(PYBRIDGE_CONFIG) as f:
        cfg = json.load(f)
    # Redact API keys for display
    safe = json.loads(json.dumps(cfg))
    for model_cfg in safe.get("models", {}).values():
        key = model_cfg.get("api_key", "")
        if key and key not in ("", "YOUR_OPENAI_API_KEY"):
            model_cfg["api_key"] = key[:8] + "..." + key[-4:]
    if "security" in safe:
        s = safe["security"].get("hmac_secret", "")
        if s:
            safe["security"]["hmac_secret"] = s[:10] + "..."
    if "email" in safe:
        p = safe["email"].get("password", "")
        if p and p != "YOUR_APP_PASSWORD":
            safe["email"]["password"] = "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"
    return safe


def write_config(data: dict):
    """Merge incoming data into the existing config and write back."""
    if not PYBRIDGE_CONFIG.exists():
        return False
    with open(PYBRIDGE_CONFIG) as f:
        cfg = json.load(f)
    _deep_merge(cfg, data)
    with open(PYBRIDGE_CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)
    return True


def _deep_merge(base: dict, overlay: dict):
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def service_status():
    """Return a dict of component statuses."""
    status = {}

    # Check PyBridge
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "pybridge.*main.py"],
            stderr=subprocess.DEVNULL, text=True
        )
        status["pybridge"] = "running" if out.strip() else "stopped"
    except subprocess.CalledProcessError:
        status["pybridge"] = "stopped"

    # Check Ollama
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "ollama"],
            stderr=subprocess.DEVNULL, text=True
        )
        status["ollama"] = "running" if out.strip() else "stopped"
    except subprocess.CalledProcessError:
        status["ollama"] = "stopped"

    # Check WhatsApp bridge (Node.js process)
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "whatsapp_bridge.*server"],
            stderr=subprocess.DEVNULL, text=True
        )
        status["whatsapp_bridge"] = "running" if out.strip() else "stopped"
    except subprocess.CalledProcessError:
        status["whatsapp_bridge"] = "stopped"

    # Runtime availability
    status["node"] = shutil.which("node") is not None
    status["python"] = sys.version.split()[0]
    status["git"] = shutil.which("git") is not None
    status["docker"] = shutil.which("docker") is not None
    status["ffmpeg"] = shutil.which("ffmpeg") is not None

    return status


def list_plugins():
    """List PyBridge plugins."""
    plugins_dir = PYBRIDGE_DIR / "plugins"
    if not plugins_dir.exists():
        return []
    plugins = []
    for f in sorted(plugins_dir.glob("*.py")):
        if f.name.startswith("_"):
            continue
        # Read the docstring for description
        desc = ""
        try:
            content = f.read_text()
            if content.startswith('"""') or content.startswith("from __future__"):
                import re
                m = re.search(r'"""(.*?)"""', content, re.DOTALL)
                if m:
                    lines = m.group(1).strip().split("\n")
                    desc = lines[0].strip().rstrip(".")
        except Exception:
            pass
        plugins.append({
            "name": f.stem.replace("_", " ").title(),
            "file": f.name,
            "size": f.stat().st_size,
            "description": desc,
        })
    return plugins


def list_channels():
    """List PyBridge channel modules."""
    channels_dir = PYBRIDGE_DIR / "channels"
    if not channels_dir.exists():
        return []
    channels = []
    for f in sorted(channels_dir.glob("*.py")):
        if f.name.startswith("_"):
            continue
        channels.append({
            "name": f.stem.replace("_", " ").title(),
            "file": f.name,
        })
    return channels


def list_engine_modules():
    """List PyBridge engine modules."""
    engine_dir = PYBRIDGE_DIR / "engine"
    if not engine_dir.exists():
        return []
    modules = []
    for f in sorted(engine_dir.glob("*.py")):
        if f.name.startswith("_") and f.name != "_direct.py":
            continue
        modules.append({
            "name": f.stem.replace("_", " ").title(),
            "file": f.name,
        })
    return modules


def check_health():
    """Return config validation warnings."""
    warnings = []
    if not PYBRIDGE_CONFIG.exists():
        return [{"level": "error", "msg": "config.json not found"}]

    with open(PYBRIDGE_CONFIG) as f:
        cfg = json.load(f)

    # Check API keys
    models = cfg.get("models", {})
    for name, m in models.items():
        key = m.get("api_key", "")
        if name != "ollama" and (not key or "YOUR_" in key):
            warnings.append({"level": "warn", "msg": f"{name}: API key not configured"})

    # Check security
    sec = cfg.get("security", {})
    hmac = sec.get("hmac_secret", "")
    if "CHANGE-ME" in hmac or "change-me" in hmac:
        warnings.append({"level": "warn", "msg": "HMAC secret is still default \u2014 generate a random one"})

    # Check channels
    any_enabled = False
    for ch in ("email", "telegram", "whatsapp", "imessage"):
        ch_cfg = cfg.get(ch, {})
        if ch_cfg.get("enabled"):
            any_enabled = True
    if not any_enabled:
        warnings.append({"level": "warn", "msg": "No channels enabled \u2014 enable at least one"})

    # Check .env
    env_path = PYBRIDGE_DIR / ".env"
    if not env_path.exists():
        warnings.append({"level": "info", "msg": ".env file not found \u2014 you can use it for secrets"})

    # Check runtime deps
    if not shutil.which("node"):
        warnings.append({"level": "info", "msg": "Node.js not found \u2014 needed for WhatsApp bridge"})

    if not warnings:
        warnings.append({"level": "ok", "msg": "Configuration looks good"})

    return warnings


# ─── HTTP handler ────────────────────────────────────────────────────

class ControlPanelHandler(SimpleHTTPRequestHandler):
    """Serves static files and a small JSON API."""

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_file(STATIC_DIR / "index.html", "text/html")
        elif self.path == "/api/status":
            self._json_response(service_status())
        elif self.path == "/api/config":
            self._json_response(read_config())
        elif self.path == "/api/plugins":
            self._json_response(list_plugins())
        elif self.path == "/api/channels":
            self._json_response(list_channels())
        elif self.path == "/api/engine":
            self._json_response(list_engine_modules())
        elif self.path == "/api/health":
            self._json_response(check_health())
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"

        if self.path == "/api/config":
            try:
                data = json.loads(body)
                ok = write_config(data)
                self._json_response({"ok": ok})
            except Exception as e:
                self._json_response({"ok": False, "error": str(e)}, 400)

        elif self.path == "/api/channel/toggle":
            try:
                data = json.loads(body)
                channel = data["channel"]
                enabled = data["enabled"]
                ok = write_config({channel: {"enabled": enabled}})
                self._json_response({"ok": ok})
            except Exception as e:
                self._json_response({"ok": False, "error": str(e)}, 400)

        elif self.path == "/api/model/default":
            try:
                data = json.loads(body)
                ok = write_config({"default_model": data["model"]})
                self._json_response({"ok": ok})
            except Exception as e:
                self._json_response({"ok": False, "error": str(e)}, 400)

        elif self.path == "/api/security":
            try:
                data = json.loads(body)
                ok = write_config({"security": data})
                self._json_response({"ok": ok})
            except Exception as e:
                self._json_response({"ok": False, "error": str(e)}, 400)

        elif self.path == "/api/contacts":
            try:
                data = json.loads(body)
                channel = data.get("channel")
                value = data.get("value")
                action = data.get("action", "add")
                
                cfg = read_config()
                
                if channel == "whatsapp":
                    contacts = cfg.setdefault("whatsapp", {}).setdefault("allowed_numbers", [])
                    if action == "add" and value not in contacts:
                        contacts.append(value)
                    elif action == "remove" and value in contacts:
                        contacts.remove(value)
                elif channel == "telegram":
                    contacts = cfg.setdefault("telegram", {}).setdefault("allowed_user_ids", [])
                    try:
                        user_id = int(value)
                        if action == "add" and user_id not in contacts:
                            contacts.append(user_id)
                        elif action == "remove" and user_id in contacts:
                            contacts.remove(user_id)
                    except ValueError:
                        self._json_response({"ok": False, "error": "Invalid Telegram user ID"}, 400)
                        return
                elif channel == "email":
                    contacts = cfg.setdefault("email", {}).setdefault("allowed_senders", [])
                    if action == "add" and value not in contacts:
                        contacts.append(value)
                    elif action == "remove" and value in contacts:
                        contacts.remove(value)
                elif channel == "imessage":
                    contacts = cfg.setdefault("imessage", {}).setdefault("allowed_handles", [])
                    if action == "add" and value not in contacts:
                        contacts.append(value)
                    elif action == "remove" and value in contacts:
                        contacts.remove(value)
                
                ok = write_config(cfg)
                self._json_response({"ok": ok})
            except Exception as e:
                self._json_response({"ok": False, "error": str(e)}, 400)

        elif self.path == "/api/contacts/list":
            try:
                cfg = read_config()
                contacts = {
                    "whatsapp": cfg.get("whatsapp", {}).get("allowed_numbers", []),
                    "telegram": cfg.get("telegram", {}).get("allowed_user_ids", []),
                    "email": cfg.get("email", {}).get("allowed_senders", []),
                    "imessage": cfg.get("imessage", {}).get("allowed_handles", []),
                }
                self._json_response(contacts)
            except Exception as e:
                self._json_response({"error": str(e)}, 400)

        else:
            self.send_error(404)

    def _json_response(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, filepath, content_type):
        filepath = Path(filepath)
        if not filepath.exists():
            self.send_error(404)
            return
        content = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        pass


# ─── main ────────────────────────────────────────────────────────────

def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT

    class ReusableHTTPServer(HTTPServer):
        allow_reuse_address = True
        allow_reuse_port = True

    server = ReusableHTTPServer((HOST, port), ControlPanelHandler)
    print(f"\n  \u2554{'═'*46}\u2557")
    print(f"  \u2551   pybridge.ai Control Panel                \u2551")
    print(f"  \u2551   http://{HOST}:{port}                    \u2551")
    print(f"  \u255a{'═'*46}\u255d\n")

    def shutdown(sig, frame):
        print("\nShutting down...")
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
