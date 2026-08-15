#!/usr/bin/env python3
"""
pybridge.ai Control Panel — lightweight web GUI for managing PyBridge.

Run:   python3 control-panel/server.py [port]
Open:  http://127.0.0.1:9090/?token=<panel token>

The panel can read and write pybridge/config.json, and config.json controls
which phone numbers may run shell commands on this machine. It is therefore
token-authenticated by default and bound to loopback by default.

  PANEL_HOST        interface to bind      (default 127.0.0.1)
  PANEL_PORT        port to bind           (default 9090)
  PANEL_TOKEN       fixed access token     (default: generated + persisted)
  PANEL_TOKEN_FILE  where to persist it    (default ~/.pybridge/panel_token)
  PANEL_AUTH=off    disable authentication (loopback-only, prints a warning)
"""

import hmac
import json
import os
import secrets
import socket
import subprocess
import sys
import signal
import shutil
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parent.parent
PYBRIDGE_DIR = ROOT / "pybridge"
PYBRIDGE_CONFIG = PYBRIDGE_DIR / "config.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"

HOST = os.environ.get("PANEL_HOST", "127.0.0.1")
PORT = int(os.environ.get("PANEL_PORT", "9090"))

COOKIE_NAME = "pybridge_panel"
TOKEN_FILE = Path(
    os.environ.get("PANEL_TOKEN_FILE") or (Path.home() / ".pybridge" / "panel_token")
)
AUTH_ENABLED = os.environ.get("PANEL_AUTH", "on").strip().lower() not in (
    "off", "0", "false", "no",
)

# Providers that run locally and legitimately have no API key.
KEYLESS_PROVIDERS = {"ollama", "opencode"}


# ─── auth ────────────────────────────────────────────────────────────

def load_or_create_token() -> str:
    """Return the panel token: env var, else persisted file, else a new one."""
    env_token = os.environ.get("PANEL_TOKEN", "").strip()
    if env_token:
        return env_token
    try:
        if TOKEN_FILE.exists():
            saved = TOKEN_FILE.read_text().strip()
            if saved:
                return saved
    except OSError:
        pass
    token = secrets.token_urlsafe(24)
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(token + "\n")
        os.chmod(TOKEN_FILE, 0o600)
    except OSError as e:
        print(f"  ! could not persist panel token to {TOKEN_FILE}: {e}")
    return token


TOKEN = load_or_create_token()


LOGIN_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>pybridge.ai — Sign in</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
background:#0f1117;color:#e1e4eb;min-height:100vh;display:flex;
align-items:center;justify-content:center;padding:24px}
.box{background:#181b24;border:1px solid #2a2e3b;border-radius:12px;
padding:32px;width:100%;max-width:400px}
h1{font-size:18px;font-weight:700;letter-spacing:-.3px;margin-bottom:6px}
h1 span{color:#6c8cff}
p{font-size:13px;color:#8b90a0;line-height:1.6;margin-bottom:20px}
input{width:100%;padding:10px 12px;background:#0f1117;border:1px solid #2a2e3b;
border-radius:8px;color:#e1e4eb;font-size:13px;outline:none}
input:focus{border-color:#6c8cff;box-shadow:0 0 0 2px rgba(108,140,255,.15)}
button{width:100%;margin-top:12px;padding:10px 16px;border:none;border-radius:8px;
background:#6c8cff;color:#fff;font-size:13px;font-weight:600;cursor:pointer}
button:hover{background:#4a64c4}
code{color:#6c8cff;font-size:12px}
.err{color:#f87171;font-size:12px;margin-top:12px;display:none}
.err.show{display:block}
</style></head><body>
<div class="box">
  <h1><span>py</span>bridge<span>.ai</span> — Control Panel</h1>
  <p>This panel can change who is allowed to run commands on this machine,
     so it needs the access token printed in the terminal that started it
     (also stored in <code>~/.pybridge/panel_token</code>).</p>
  <form onsubmit="go(event)">
    <input id="tok" type="password" placeholder="Access token" autofocus>
    <button type="submit">Unlock</button>
  </form>
  <div class="err" id="err">Invalid token.</div>
</div>
<script>
if (new URLSearchParams(location.search).get('token')) {
  document.getElementById('err').classList.add('show');
}
function go(e){
  e.preventDefault();
  const t = document.getElementById('tok').value.trim();
  if (t) location.href = '/?token=' + encodeURIComponent(t);
}
</script>
</body></html>
"""


# ─── helpers ─────────────────────────────────────────────────────────

def load_config_raw() -> dict:
    """Read config.json verbatim — secrets included. Never send this to a client."""
    if not PYBRIDGE_CONFIG.exists():
        return {}
    with open(PYBRIDGE_CONFIG) as f:
        return json.load(f)


def read_config():
    """Read the PyBridge config.json for display (redacting secrets).

    The result is lossy: it MUST NOT be fed back into write_config(), or the
    redacted placeholders overwrite the real secrets on disk.
    """
    cfg = load_config_raw()
    if not cfg:
        return {}
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
            safe["email"]["password"] = "••••••••"
    return safe


def write_config(data: dict):
    """Merge incoming data into the existing config and write back.

    `data` must be a *delta* built from load_config_raw() (or from client
    input), never the redacted dict returned by read_config().
    """
    if not PYBRIDGE_CONFIG.exists():
        return False
    cfg = load_config_raw()
    _deep_merge(cfg, data)
    tmp = PYBRIDGE_CONFIG.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, PYBRIDGE_CONFIG)
    return True


def _deep_merge(base: dict, overlay: dict):
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


CONTACT_FIELDS = {
    "whatsapp": "allowed_numbers",
    "telegram": "allowed_user_ids",
    "email": "allowed_senders",
    "imessage": "allowed_handles",
}


def list_contacts() -> dict:
    cfg = load_config_raw()
    return {
        channel: list(cfg.get(channel, {}).get(field, []))
        for channel, field in CONTACT_FIELDS.items()
    }


def update_contact(channel: str, value, action: str) -> tuple[bool, str]:
    """Add/remove one allowlist entry. Writes only that one list back."""
    field = CONTACT_FIELDS.get(channel)
    if not field:
        return False, f"Unknown channel: {channel}"
    if value is None or str(value).strip() == "":
        return False, "Empty contact value"

    if channel == "telegram":
        try:
            value = int(str(value).strip())
        except ValueError:
            return False, "Invalid Telegram user ID"
    else:
        value = str(value).strip()

    cfg = load_config_raw()
    contacts = list(cfg.get(channel, {}).get(field, []))
    if action == "add":
        if value not in contacts:
            contacts.append(value)
    elif action == "remove":
        contacts = [c for c in contacts if c != value]
    else:
        return False, f"Unknown action: {action}"

    # Delta only — everything else in config.json is left untouched.
    return write_config({channel: {field: contacts}}), ""


def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _pgrep(pattern: str) -> bool:
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", pattern], stderr=subprocess.DEVNULL, text=True
        )
        return bool(out.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _url_host_port(url: str, default_port: int) -> tuple[str, int]:
    parts = urlsplit(url or "")
    return (parts.hostname or "127.0.0.1", parts.port or default_port)


def service_status():
    """Return a dict of component statuses."""
    cfg = load_config_raw()
    status = {}

    status["pybridge"] = "running" if _pgrep("pybridge.*main.py") else "stopped"

    ollama_url = cfg.get("models", {}).get("ollama", {}).get(
        "base_url", "http://localhost:11434")
    status["ollama"] = "running" if _port_open(*_url_host_port(ollama_url, 11434)) else "stopped"

    opencode_url = cfg.get("models", {}).get("opencode", {}).get(
        "base_url", "http://localhost:54321")
    status["opencode"] = "running" if _port_open(*_url_host_port(opencode_url, 54321)) else "stopped"

    bridge_port = int(cfg.get("whatsapp", {}).get("bridge_port", 8766))
    bridge_up = _port_open("127.0.0.1", bridge_port) or _pgrep("whatsapp_bridge.*server")
    status["whatsapp_bridge"] = "running" if bridge_up else "stopped"

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

    cfg = load_config_raw()

    # Check API keys — only for remote providers that actually need one, and
    # only warn loudly for models the fallback chain will really reach.
    models = cfg.get("models", {})
    in_use = [cfg.get("default_model", "")] + list(cfg.get("fallback_chain", []))
    for name, m in models.items():
        if m.get("provider", name) in KEYLESS_PROVIDERS:
            continue
        key = m.get("api_key", "")
        if not key or "YOUR_" in key:
            level = "warn" if name in in_use else "info"
            suffix = "" if level == "warn" else " (unused — not in fallback chain)"
            warnings.append({"level": level,
                             "msg": f"{name}: API key not configured{suffix}"})

    # Check security
    sec = cfg.get("security", {})
    hmac_secret = sec.get("hmac_secret", "")
    if "CHANGE-ME" in hmac_secret or "change-me" in hmac_secret:
        warnings.append({"level": "info", "msg": "HMAC secret is still the default value"})

    # Check channels
    any_enabled = any(cfg.get(ch, {}).get("enabled")
                      for ch in ("email", "telegram", "whatsapp", "imessage"))
    if not any_enabled:
        warnings.append({"level": "warn",
                         "msg": "No messaging channel enabled — enable one, "
                                "or run the daemon with: python main.py --repl"})

    # Check .env
    env_path = PYBRIDGE_DIR / ".env"
    if not env_path.exists():
        warnings.append({"level": "info", "msg": ".env file not found — you can use it for secrets"})

    # Check runtime deps
    if not shutil.which("node"):
        warnings.append({"level": "info", "msg": "Node.js not found — needed for WhatsApp bridge"})

    if not AUTH_ENABLED:
        warnings.append({"level": "warn",
                         "msg": "Panel authentication is DISABLED (PANEL_AUTH=off)"})
    if HOST not in ("127.0.0.1", "localhost", "::1") and not AUTH_ENABLED:
        warnings.append({"level": "error",
                         "msg": f"Panel is bound to {HOST} with no authentication"})

    if not any(w["level"] in ("warn", "error") for w in warnings):
        warnings.insert(0, {"level": "ok", "msg": "Configuration looks good"})

    return warnings


# ─── HTTP handler ────────────────────────────────────────────────────

class ControlPanelHandler(SimpleHTTPRequestHandler):
    """Serves static files and a small JSON API, behind a token gate."""

    server_version = "PyBridgePanel/1.0"

    # ── auth ──────────────────────────────────────────────────────────

    def _request_token(self, query: dict) -> str:
        qs_token = (query.get("token") or [""])[0]
        if qs_token:
            return qs_token
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        header_token = self.headers.get("X-Panel-Token", "")
        if header_token:
            return header_token.strip()
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE_NAME:
                return value
        return ""

    def _authorized(self, query: dict) -> bool:
        if not AUTH_ENABLED:
            return True
        return hmac.compare_digest(self._request_token(query), TOKEN)

    def _cookie_header(self) -> list[tuple[str, str]]:
        return [("Set-Cookie",
                 f"{COOKIE_NAME}={TOKEN}; Path=/; Max-Age=604800; "
                 f"HttpOnly; SameSite=Strict")]

    # ── routes ────────────────────────────────────────────────────────

    def do_GET(self):
        path, query = self._split_path()

        # Liveness probe for Docker/k8s. Deliberately unauthenticated and
        # deliberately reveals nothing about the configuration.
        if path == "/healthz":
            self._json_response({"status": "ok"})
            return

        if path in ("/", "/index.html"):
            if not self._authorized(query):
                self._send_bytes(LOGIN_PAGE.encode(), "text/html", code=401)
                return
            # A token in the URL becomes a cookie so the page's fetch() calls
            # (and any reload) stay authenticated without it in every link.
            extra = self._cookie_header() if query.get("token") else []
            self._serve_file(STATIC_DIR / "index.html", "text/html", extra)
            return

        if not self._authorized(query):
            self._json_response({"error": "unauthorized"}, 401)
            return

        routes = {
            "/api/status": service_status,
            "/api/config": read_config,
            "/api/plugins": list_plugins,
            "/api/channels": list_channels,
            "/api/engine": list_engine_modules,
            "/api/health": check_health,
            "/api/contacts/list": list_contacts,
        }
        handler = routes.get(path)
        if handler is None:
            self.send_error(404)
            return
        self._json_response(handler())

    def do_POST(self):
        path, query = self._split_path()

        if not self._authorized(query):
            self._json_response({"error": "unauthorized"}, 401)
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"

        try:
            data = json.loads(body or b"{}")
        except ValueError as e:
            self._json_response({"ok": False, "error": f"Invalid JSON: {e}"}, 400)
            return
        if not isinstance(data, dict):
            self._json_response({"ok": False, "error": "Expected a JSON object"}, 400)
            return

        try:
            if path == "/api/config":
                self._json_response({"ok": write_config(data)})

            elif path == "/api/channel/toggle":
                ok = write_config({data["channel"]: {"enabled": bool(data["enabled"])}})
                self._json_response({"ok": ok})

            elif path == "/api/model/default":
                model = data["model"]
                if model not in load_config_raw().get("models", {}):
                    self._json_response({"ok": False, "error": f"Unknown model: {model}"}, 400)
                    return
                self._json_response({"ok": write_config({"default_model": model})})

            elif path == "/api/security":
                self._json_response({"ok": write_config({"security": data})})

            elif path == "/api/contacts":
                ok, err = update_contact(
                    data.get("channel"), data.get("value"), data.get("action", "add")
                )
                if err:
                    self._json_response({"ok": False, "error": err}, 400)
                else:
                    self._json_response({"ok": ok})

            elif path == "/api/contacts/list":
                self._json_response(list_contacts())

            else:
                self.send_error(404)
        except KeyError as e:
            self._json_response({"ok": False, "error": f"Missing field: {e}"}, 400)
        except Exception as e:
            self._json_response({"ok": False, "error": str(e)}, 400)

    # ── plumbing ──────────────────────────────────────────────────────

    def _split_path(self) -> tuple[str, dict]:
        parts = urlsplit(self.path)
        return parts.path, parse_qs(parts.query)

    def _send_bytes(self, content: bytes, content_type: str, code: int = 200,
                    extra_headers=()):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in extra_headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content)

    def _json_response(self, data, code=200):
        self._send_bytes(json.dumps(data).encode(), "application/json", code)

    def _serve_file(self, filepath, content_type, extra_headers=()):
        filepath = Path(filepath)
        if not filepath.exists():
            self.send_error(404)
            return
        self._send_bytes(filepath.read_bytes(), content_type, 200, extra_headers)

    def log_message(self, format, *args):
        pass


# ─── main ────────────────────────────────────────────────────────────

def build_server(port: int) -> ThreadingHTTPServer:
    class ReusableHTTPServer(ThreadingHTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    return ReusableHTTPServer((HOST, port), ControlPanelHandler)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    server = build_server(port)

    url = f"http://{HOST if HOST != '0.0.0.0' else '127.0.0.1'}:{port}"
    title = "pybridge.ai Control Panel"
    width = 62
    print(f"\n  ╔{'═' * width}╗")
    print(f"  ║  {title.ljust(width - 2)}║")
    print(f"  ╚{'═' * width}╝\n")
    if AUTH_ENABLED:
        print(f"  Open: {url}/?token={TOKEN}")
        if not os.environ.get("PANEL_TOKEN", "").strip():
            print(f"  Token file: {TOKEN_FILE}")
    else:
        print(f"  Open: {url}")
        print("  ! PANEL_AUTH=off — anyone who can reach this port has full control")
    print(f"  Bound to {HOST}:{port}   (Ctrl-C to stop)\n", flush=True)

    def shutdown(sig, frame):
        print("\nShutting down...")
        # server.shutdown() blocks until serve_forever() returns, so it can
        # never be called from the thread that is inside serve_forever().
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
