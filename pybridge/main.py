from __future__ import annotations
"""
PyBridge — Secure AI Remote Control Daemon

Architecture:
  Phone (1 authorized contact)
    │ Email (TLS) / Telegram / WhatsApp / iMessage
    ▼
  PyBridge — security gate + channel handler + command router
    │ direct API calls
    ├── Claude  (Anthropic API)
    ├── Codex   (OpenAI API)
    └── Ollama  (local, no API key needed)

Security:
  - One authorized contact per channel
  - Prompt injection detection and blocking
  - Rate limiting per identity
  - All external comms over TLS
  - Model fallback chain with automatic retry + backoff
"""

import json
import os
import sys
import time
import logging
import platform
import imaplib
import smtplib
import email
import email.utils
import threading
import subprocess
import shutil
import tempfile
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.header import decode_header

import security
import screen
import meet
from channels import whatsapp as wa_channel
from channels import imessage as im_channel
from plugins import git_github
from plugins import log_watcher
from plugins import process_monitor
from plugins import docker_mgr
from plugins import code_runner
from plugins import file_ops
from plugins import scheduler
from plugins import clipboard
from plugins import browser
from plugins import packages
from plugins import vscode

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pybridge")

# ── Config ────────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OS = platform.system()

# Load .env if present (secrets override config.json placeholders)
_env_path = os.path.join(BASE_DIR, ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

with open(os.path.join(BASE_DIR, "config.json")) as f:
    CONFIG = json.load(f)

# Inject .env values into CONFIG
if os.environ.get("ANTHROPIC_API_KEY"):
    CONFIG["models"]["claude"]["api_key"] = os.environ["ANTHROPIC_API_KEY"]
if os.environ.get("OPENAI_API_KEY"):
    CONFIG["models"]["codex"]["api_key"] = os.environ["OPENAI_API_KEY"]
if os.environ.get("EMAIL_ADDRESS"):
    CONFIG["email"]["address"] = os.environ["EMAIL_ADDRESS"]
if os.environ.get("EMAIL_PASSWORD"):
    CONFIG["email"]["password"] = os.environ["EMAIL_PASSWORD"]
if os.environ.get("TELEGRAM_BOT_TOKEN"):
    CONFIG["telegram"]["bot_token"] = os.environ["TELEGRAM_BOT_TOKEN"]
if os.environ.get("HMAC_SECRET"):
    CONFIG["security"]["hmac_secret"] = os.environ["HMAC_SECRET"]
if os.environ.get("WHATSAPP_NUMBER"):
    CONFIG["whatsapp"]["allowed_numbers"] = [os.environ["WHATSAPP_NUMBER"]]

SEC = CONFIG["security"]

current_model = CONFIG["default_model"]

# ── OpenCode helper functions ────────────────────────────────────────────────

_opencode_sessions: dict[str, str] = {}

def _check_opencode_health() -> str:
    cfg = CONFIG["models"].get("opencode", {})
    base_url = cfg.get("base_url", "http://localhost:54321")
    healthy = providers.opencode_health(base_url)
    if healthy:
        return f"OpenCode server is healthy at {base_url}"
    return f"OpenCode server NOT reachable at {base_url}"

def _list_opencode_sessions() -> str:
    cfg = CONFIG["models"].get("opencode", {})
    base_url = cfg.get("base_url", "http://localhost:54321")
    sessions = providers.opencode_sessions(base_url)
    if not sessions:
        return "No active OpenCode sessions. Use 'oc run <prompt>' to start one."
    lines = ["OpenCode Sessions:"]
    for s in sessions:
        sid = s.get("id", "?")
        title = s.get("title", s.get("name", "Untitled"))
        lines.append(f"  {sid[:12]}... - {title}")
    return "\n".join(lines)

def _attach_opencode_session(session_id: str) -> str:
    global _opencode_sessions
    _opencode_sessions["default"] = session_id
    return f"Attached to session {session_id[:12]}..."

def _handle_opencode(args: str) -> str:
    cfg = CONFIG["models"].get("opencode", {})
    base_url = cfg.get("base_url", "http://localhost:54321")
    model = cfg.get("model", "claude-sonnet-4-20250514")

    if not args:
        return "Usage: oc run <prompt> | oc sessions | oc health"

    parts = args.split(None, 1)
    cmd = parts[0]

    if cmd == "run" and len(parts) > 1:
        prompt = parts[1]
        try:
            resp = providers.opencode_send_message("default", prompt, base_url)
            if isinstance(resp, dict):
                data = resp.get("data", {})
                if isinstance(data, dict):
                    return data.get("result", str(resp))
            return str(resp)
        except Exception as e:
            session = providers.opencode_create_session(base_url)
            if session:
                sid = session.get("id", "default")
                _opencode_sessions["default"] = sid
                try:
                    resp = providers.opencode_send_message(sid, prompt, base_url)
                    data = resp.get("data", {}) if isinstance(resp, dict) else {}
                    return data.get("result", str(resp))
                except Exception as e2:
                    return f"Error: {e2}"
            return f"Error creating session: {e}"

    if cmd == "sessions":
        return _list_opencode_sessions()

    if cmd == "health":
        return _check_opencode_health()

    return f"Unknown opencode command: {cmd}. Use: run, sessions, health"

# ── AI Engine ─────────────────────────────────────────────────────────────────

from engine.session import SessionManager
from engine.runner  import AgentRunner
from engine import providers

_sessions_dir = os.environ.get("PYBRIDGE_SESSIONS_DIR") or os.path.expanduser(CONFIG.get("sessions_dir", "~/.pybridge/sessions"))
_session_mgr  = SessionManager(_sessions_dir)
_runner       = AgentRunner(CONFIG, _session_mgr)


def ask_ai(prompt: str, identity: str) -> str | None:
    """
    Send prompt to AI engine.
    Uses active model, maintains per-identity session history,
    auto-falls back to next model on failure.
    """
    try:
        result = _runner.run(prompt, identity, current_model)
        provider = result["provider_used"]
        model    = result["model_used"]
        usage    = result["usage"]
        log.info(f"[ai] {provider}/{model} | in={usage['input']} out={usage['output']}")
        return result["text"]
    except Exception as e:
        log.warning(f"[ai] LLM failed: {e}")
        return None

def ask_ai_with_fallback(prompt: str, identity: str) -> tuple[str, str | None]:
    """
    Try AI first, if all fail fall back to direct command mode.
    Returns (reply, file_path)
    """
    result = ask_ai(prompt, identity)
    if result:
        return f"[{current_model}]\n\n{result}", None
    
    log.info("[ai] All LLMs failed, falling back to direct command mode")
    return _handle_direct_command(prompt, identity)

# ── Direct command mode (when LLM unavailable) ─────────────────────────────────

ALLOWED_COMMANDS = {
    "system": ["ps", "top", "htop", "uptime", "df", "du", "free", "hostname", "uname", "whoami", "date", "cal"],
    "process": ["ps aux", "kill", "pkill", "pgrep", "top", "htop"],
    "network": ["ipconfig", "ifconfig", "ping", "netstat", "ss", "curl", "wget", "hostname -I", "arp", "traceroute"],
    "docker": ["docker ps", "docker ps -a", "docker images", "docker logs", "docker stats", "docker inspect"],
    "git": ["git status", "git log --oneline -5", "git diff", "git branch -a", "git remote -v"],
    "files": ["ls", "ls -la", "ls -lh", "pwd", "cat", "head", "tail", "wc", "find", "grep"],
    "screen": ["screenshot", "ss", "record"],
    "clipboard": ["clip", "paste", "copy"],
    "meet": ["meet zoom", "meet google", "meet teams"],
}

DIRECT_COMMANDS = {
    "ps": "ps aux | head -20",
    "cpu": "top -bn1 | head -10",
    "mem": "free -h",
    "disk": "df -h",
    "ports": "netstat -tulpn 2>/dev/null || ss -tulpn",
    "uptime": "uptime",
    "hostname": "hostname",
    "ip": "hostname -I",
    "docker ps": "docker ps",
    "docker logs": "docker logs",
    "docker stats": "docker stats --no-stream",
    "git status": "git status",
    "git log": "git log --oneline -5",
    "git diff": "git diff --stat",
    "ls": "ls -la",
    "pwd": "pwd",
}


def _handle_direct_command(prompt: str, identity: str) -> tuple[str, str | None]:
    """
    Handle commands directly when LLM is unavailable.
    Maps natural language to allowed commands.
    """
    lower = prompt.lower().strip()
    
    # Check exact matches first
    for cmd, output in DIRECT_COMMANDS.items():
        if lower == cmd or lower.startswith(cmd + " "):
            extra = prompt[len(cmd):].strip() if len(prompt) > len(cmd) else ""
            full_cmd = output + (" " + extra if extra else "")
            result = _run_shell(full_cmd)
            return f"$ {full_cmd}\n\n{result}", None
    
    # Check screenshot/record
    if lower in ("screenshot", "ss", "snap"):
        try:
            path = screen.take_screenshot()
            return "Screenshot taken.", path
        except Exception as e:
            return f"Screenshot failed: {e}", None
    
    if lower.startswith("record "):
        parts = lower.split()
        seconds = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
        path, err = screen.record_screen(seconds)
        if err:
            return f"Recording failed: {err}", None
        return f"Screen recorded ({seconds}s).", path
    
    # Check video calls
    if lower.startswith("facetime ") or lower == "facetime":
        return _start_facetime(prompt), None
    
    if lower.startswith("whatsapp call") or lower.startswith("wa call"):
        return _start_whatsapp_call(prompt), None
    
    if lower.startswith("zoom") or lower.startswith("meet zoom"):
        return meet.handle_meet("zoom", CONFIG.get("meeting", {})), None
    
    if lower.startswith("google meet") or lower.startswith("meet google"):
        return meet.handle_meet("google", CONFIG.get("meeting", {})), None
    
    if lower.startswith("teams") or lower.startswith("meet teams"):
        return meet.handle_meet("teams", CONFIG.get("meeting", {})), None
    
    # Clipboard
    if lower in ("clip", "clipboard", "paste"):
        return clipboard.handle(lower, ""), None
    
    if lower.startswith("copy "):
        return clipboard.handle("copy", prompt[5:].strip()), None
    
    # Help for direct mode
    if lower in ("help", "commands", "?"):
        return (
            "Direct Command Mode (LLM unavailable)\n\n"
            "System:\n"
            "  ps, cpu, mem, disk, ports, uptime, hostname, ip\n\n"
            "Docker:\n"
            "  docker ps, docker logs, docker stats\n\n"
            "Git:\n"
            "  git status, git log, git diff\n\n"
            "Screen:\n"
            "  ss, screenshot, record 10\n\n"
            "Video Calls:\n"
            "  facetime <name/number>\n"
            "  whatsapp call <number>\n"
            "  zoom, google meet, teams\n\n"
            "Clipboard:\n"
            "  clip, copy <text>"
        ), None
    
    return (
        "LLM unavailable. Use direct commands:\n"
        "  ps, cpu, mem, disk, ports, uptime\n"
        "  docker ps, docker logs, git status\n"
        "  ss, screenshot, record\n"
        "  facetime <contact>, whatsapp call <number>\n"
        "  zoom, google meet, teams\n"
        "  help for more"
    ), None


def _start_facetime(args: str) -> str:
    """Start FaceTime call"""
    import subprocess
    contact = args.replace("facetime", "").strip()
    if not contact:
        return "Usage: facetime <name or number>"
    try:
        if OS == "Darwin":
            subprocess.run(["open", f"facetime:{contact}"], check=True)
            return f"Starting FaceTime call with {contact}..."
        else:
            return "FaceTime is only available on macOS"
    except Exception as e:
        return f"Failed to start FaceTime: {e}"


def _start_whatsapp_call(args: str) -> str:
    """Start WhatsApp call"""
    import subprocess
    number = args.replace("whatsapp call", "").replace("wa call", "").strip()
    if not number:
        return "Usage: whatsapp call <number>"
    try:
        subprocess.run(["open", f"whatsapp://send?phone={number}"], check=True)
        return f"Opening WhatsApp to call {number}..."
    except Exception as e:
        return f"Failed to start WhatsApp call: {e}"


def list_models() -> str:
    return _runner.list_models()


def switch_model(target: str, extra: str = "") -> str:
    global current_model
    models = CONFIG["models"]
    if target in models:
        if target == "ollama" and extra:
            models["ollama"]["model"] = extra
            _runner._build_catalog()   # rebuild so new model is picked up
        current_model = target
        model_name = models[current_model]["model"]
        return f"Switched to {current_model} ({model_name})"
    return f"Unknown model '{target}'. Available: {', '.join(models.keys())}"

# ── Command Router ────────────────────────────────────────────────────────────

def handle_command(text: str, identity: str) -> tuple[str, str | None]:
    """
    Security-gate then route command.
    Returns (reply_text, file_path_or_None).
    """
    # ── Security gate ──────────────────────────────────────────────────────
    allowed, result = security.gate(text, identity, SEC)
    if not allowed:
        log.warning(f"Message from {identity} blocked: {result}")
        return f"Blocked: {result}", None
    text = result  # sanitized text

    lower = text.lower()

    # ── Model switching ────────────────────────────────────────────────────
    if lower.startswith("use "):
        parts = text.split()
        target = parts[1].lower() if len(parts) > 1 else ""
        extra = parts[2] if len(parts) > 2 else ""
        return switch_model(target, extra), None

    if lower in ("model", "model?", "which model", "current model"):
        cfg = CONFIG["models"].get(current_model, {})
        return f"Current: {current_model} → {cfg.get('model', '?')}", None

    if lower in ("models", "list models", "available models"):
        return list_models(), None

    # ── Screen tools ───────────────────────────────────────────────────────
    if lower in ("screenshot", "ss", "screen", "snap"):
        try:
            path = screen.take_screenshot()
            return "Screenshot taken.", path
        except Exception as e:
            return f"Screenshot failed: {e}", None

    if lower.startswith("record"):
        parts = lower.split()
        seconds = 10
        if len(parts) > 1:
            try:
                seconds = int(parts[1])
            except ValueError:
                pass
        path, err = screen.record_screen(seconds)
        if err:
            return f"Recording failed: {err}", None
        return f"Screen recorded ({seconds}s).", path

    if lower in ("stream", "start stream", "live", "livestream"):
        port = CONFIG.get("stream", {}).get("port", 8765)
        return screen.start_stream(port), None

    if lower in ("stopstream", "stop stream", "endstream"):
        return screen.stop_stream(), None

    # ── Meeting ────────────────────────────────────────────────────────────
    if lower.startswith("meet"):
        args = text[4:].strip()
        return meet.handle_meet(args, CONFIG.get("meeting", {})), None

    if lower.startswith("whatsapp call") or lower.startswith("wa call") or lower.startswith("whatsapp video"):
        number = text.split()[-1] if text.split() else ""
        return meet.start_whatsapp_video(number), None

    # ── Terminal command ───────────────────────────────────────────────────
    if lower.startswith("run "):
        cmd = text[4:].strip()
        output = _run_shell(cmd)
        return f"$ {cmd}\n\n{output}", None

    # ── History ────────────────────────────────────────────────────────────
    if lower in ("clear", "clear history", "reset", "new chat"):
        _session_mgr.clear(identity)
        return "Conversation history cleared. Fresh start.", None

    if lower in ("status", "ping"):
        sessions = _session_mgr.list_sessions()
        cfg = CONFIG["models"].get(current_model, {})
        return (
            f"PyBridge status\n"
            f"  OS       : {OS}\n"
            f"  Model    : {current_model} ({cfg.get('provider','?')}/{cfg.get('model','?')})\n"
            f"  Fallback : {' → '.join(CONFIG.get('fallback_chain', []))}\n"
            f"  Sessions : {len(sessions)}"
        ), None

    # ── OS info ────────────────────────────────────────────────────────────
    if lower in ("os", "system", "platform"):
        return f"Running on {OS} ({platform.platform()})", None

    # ── Help ───────────────────────────────────────────────────────────────
    if lower in ("help", "commands", "?"):
        return (
            f"PyBridge on {OS}\n\n"
            "AI:\n"
            "  use claude / codex / ollama   switch model\n"
            "  use ollama <name>             specific ollama model\n"
            "  model / models               show current / list all\n"
            "  clear                        reset chat history\n\n"
            "Screen:\n"
            "  ss / screenshot              take screenshot\n"
            "  record 10                    record 10s video\n"
            "  stream / stopstream          live screen stream\n\n"
            "Meetings:\n"
            "  meet zoom/google/teams       start video meeting\n\n"
            "Git & GitHub:\n"
            "  git status / log / diff      git info\n"
            "  git pull / push              sync\n"
            "  pr list / pr create <title>  pull requests\n"
            "  issue list / issue <num>     GitHub issues\n"
            "  deploy                       CI/CD status\n\n"
            "System:\n"
            "  ps / ps <name>               processes\n"
            "  kill <name/pid>              kill process\n"
            "  cpu / mem / disk             system resources\n"
            "  ports                        open ports\n"
            "  uptime / sys                 system overview\n\n"
            "Docker:\n"
            "  docker ps / logs / restart   containers\n"
            "  docker stop/start/stats      container control\n"
            "  compose up/down/logs         docker compose\n\n"
            "Code Runner:\n"
            "  py <code>                    run Python\n"
            "  node <code>                  run Node.js\n"
            "  bash <cmd>                   run bash\n"
            "  sql <query>                  run SQL\n"
            "  http GET <url>               HTTP request\n\n"
            "Files:\n"
            "  read <file> [lines]          view file\n"
            "  search <pattern>             grep codebase\n"
            "  find <pattern>               find files\n"
            "  tree [path]                  directory tree\n"
            "  open <file>                  open in VS Code\n\n"
            "Scheduler:\n"
            "  every 30m screenshot         recurring task\n"
            "  at 09:00 git status          daily at time\n"
            "  crons                        list tasks\n"
            "  cancel <id>                  cancel task\n\n"
            "Log Watcher:\n"
            "  watch <path>                 watch log file\n"
            "  tail <path> [lines]          tail log\n"
            "  watchers / unwatch <path>    manage watchers\n\n"
            "Browser:\n"
            "  browse <url>                 screenshot URL\n"
            "  title <url>                  page title\n"
            "  fetch <url>                  page text\n\n"
            "Packages:\n"
            "  npm check / audit            npm outdated/security\n"
            "  pip check / audit            pip outdated/security\n"
            "  audit                        run all audits\n\n"
            "Clipboard:\n"
            "  clip                         read clipboard\n"
            "  copy <text>                  set clipboard\n\n"
            "VS Code:\n"
            "  vscode open <file>           open in VS Code\n"
            "  vscode ext list/install      extensions\n\n"
            "OpenCode:\n"
            "  oc run <prompt>              run prompt in OpenCode\n"
            "  oc sessions                  list sessions\n"
            "  oc attach <id>              attach to session\n"
            "  oc health                    check server health\n"
            "  use opencode                 switch to OpenCode model\n\n"
            "  run <cmd>                    any terminal command\n"
            "  status / help                info"
        ), None

    # ── Git / GitHub ───────────────────────────────────────────────────────
    GIT_CMDS = (
        "git status", "git log", "git diff", "git pull", "git push",
        "git branches", "git stash", "gst", "glog", "log", "diff",
        "pull", "push", "branches", "stash",
        "pr list", "pr status", "pr create", "pr view", "pr merge",
        "prs", "issue list", "issues", "issue", "deploy", "ci", "workflow",
    )
    for gc in GIT_CMDS:
        if lower == gc or lower.startswith(gc + " "):
            args = text[len(gc):].strip()
            return git_github.handle(gc, args), None

    # ── Log watcher ────────────────────────────────────────────────────────
    if lower.startswith("watch") or lower in ("watchers", "watching"):
        parts = lower.split(None, 1)
        cmd = parts[0]
        args = text.split(None, 1)[1] if " " in text else ""
        return log_watcher.handle(cmd, args), None

    if lower.startswith("unwatch"):
        args = text[7:].strip()
        return log_watcher.handle("unwatch", args), None

    if lower.startswith("tail "):
        return log_watcher.handle("tail", text[5:].strip()), None

    # ── Process / system monitor ───────────────────────────────────────────
    PROC_CMDS = ("ps", "kill", "ports", "listening", "disk", "mem", "memory",
                 "ram", "cpu", "sys", "system", "overview", "uptime")
    for pc in PROC_CMDS:
        if lower == pc or lower.startswith(pc + " "):
            args = text[len(pc):].strip()
            return process_monitor.handle(pc, args), None

    # ── Docker ─────────────────────────────────────────────────────────────
    DOCKER_CMDS = (
        "docker ps", "docker logs", "docker restart", "docker stop",
        "docker start", "docker stats", "docker images", "docker pull",
        "docker exec", "docker prune", "docker clean", "containers",
        "compose up", "compose down", "compose logs", "compose restart",
        "compose pull", "compose ps",
    )
    for dc in DOCKER_CMDS:
        if lower == dc or lower.startswith(dc + " "):
            args = text[len(dc):].strip()
            return docker_mgr.handle(dc, args), None

    # ── Code runner ────────────────────────────────────────────────────────
    CODE_CMDS = ("py", "node", "bash", "sh", "ruby", "go", "sql", "http", "get", "post")
    for cc in CODE_CMDS:
        if lower.startswith(cc + " "):
            args = text[len(cc):].strip()
            return code_runner.handle(cc, args), None

    # ── File operations ────────────────────────────────────────────────────
    FILE_CMDS = ("read", "search", "grep", "find", "locate", "open", "tree", "wc", "wordcount")
    for fc in FILE_CMDS:
        if lower == fc or lower.startswith(fc + " "):
            args = text[len(fc):].strip()
            return file_ops.handle(fc, args), None

    # ── Scheduler ──────────────────────────────────────────────────────────
    if lower.startswith("every "):
        args = text[6:].strip()
        return scheduler.handle("every", args, handle_command), None

    if lower.startswith("at "):
        args = text[3:].strip()
        return scheduler.handle("at", args, handle_command), None

    if lower in ("crons", "scheduled", "tasks", "jobs"):
        return scheduler.handle(lower, "", handle_command), None

    if lower.startswith("cancel ") or lower.startswith("unschedule "):
        cmd, _, args = lower.partition(" ")
        return scheduler.handle(cmd, args.strip(), handle_command), None

    # ── Clipboard ──────────────────────────────────────────────────────────
    if lower in ("clip", "clipboard", "paste"):
        return clipboard.handle(lower, ""), None

    if lower.startswith("copy "):
        return clipboard.handle("copy", text[5:].strip()), None

    # ── Browser ────────────────────────────────────────────────────────────
    if lower.startswith("browse "):
        reply, path = browser.handle("browse", text[7:].strip())
        return reply, path

    if lower.startswith("title "):
        return browser.handle("title", text[6:].strip())

    if lower.startswith("fetch ") or lower.startswith("curl "):
        cmd, _, args = lower.partition(" ")
        return browser.handle(cmd, args.strip())

    # ── Packages ───────────────────────────────────────────────────────────
    PKG_CMDS = ("npm check", "npm audit", "npm install", "npm list",
                "pip check", "pip audit", "pip install", "pip list", "audit")
    for pkc in PKG_CMDS:
        if lower == pkc or lower.startswith(pkc + " "):
            args = text[len(pkc):].strip()
            return packages.handle(pkc, args), None

    # ── VS Code ────────────────────────────────────────────────────────────
    if lower.startswith("vscode") or lower.startswith("code "):
        return vscode.handle("vscode", text.split(None, 1)[1] if " " in text else ""), None

    # ── OpenCode ───────────────────────────────────────────────────────────────
    if lower.startswith("opencode ") or lower.startswith("oc "):
        return _handle_opencode(text[len(lower.split()[0])+1:].strip()), None

    if lower in ("opencode", "oc", "oc sessions", "opencode sessions"):
        return _list_opencode_sessions(), None

    if lower.startswith("oc attach ") or lower.startswith("opencode attach "):
        args = text.split(None, 1)[1].strip()
        return _attach_opencode_session(args), None

    if lower in ("opencode health", "oc health"):
        return _check_opencode_health(), None

    if lower in ("opencode models", "oc models"):
        return "Use any model via OpenCode provider. Configure in config.json.", None

    # ── Forward to AI ─────────────────────────────────────────────────────
    reply, file_path = ask_ai_with_fallback(text, identity)
    return reply, file_path

def _run_shell(cmd: str) -> str:
    try:
        kwargs = {}
        if OS == "Windows":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, **kwargs)
        else:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30,
                executable=shutil.which("bash") or "/bin/sh"
            )
        out = result.stdout.strip()
        err = result.stderr.strip()
        combined = out + (f"\n[stderr]\n{err}" if err and out else err if err else "")
        return combined[:3000] or "(no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out (30s limit)"
    except Exception as e:
        return f"Error: {e}"

# ── Email Channel ─────────────────────────────────────────────────────────────

def send_email(to_addr: str, subject: str, body: str, attachment_path: str | None = None):
    cfg = CONFIG["email"]
    msg = MIMEMultipart()
    msg["From"] = cfg["address"]
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if attachment_path and os.path.exists(attachment_path):
        filename = os.path.basename(attachment_path)
        ctype = "image/png" if attachment_path.endswith(".png") else "video/mp4"
        maintype, subtype = ctype.split("/")
        with open(attachment_path, "rb") as f:
            part = MIMEBase(maintype, subtype)
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)
        os.remove(attachment_path)

    with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as server:
        server.starttls()
        server.login(cfg["address"], cfg["password"])
        server.send_message(msg)

def fetch_unread_emails() -> list[dict]:
    cfg = CONFIG["email"]
    results = []
    try:
        mail = imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"])
        mail.login(cfg["address"], cfg["password"])
        mail.select("inbox")
        _, data = mail.search(None, "UNSEEN")
        for num in data[0].split():
            _, msg_data = mail.fetch(num, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            from_raw = msg.get("From", "")
            sender = email.utils.parseaddr(from_raw)[1].lower()

            # ── Authorization: only allowed senders ──────────────────────
            allowed = cfg.get("allowed_senders", [])
            if not security.verify_email_sender(sender, allowed):
                continue

            subj_raw = msg.get("Subject", "")
            subj_parts = decode_header(subj_raw)
            subject = "".join(
                part.decode(enc or "utf-8") if isinstance(part, bytes) else part
                for part, enc in subj_parts
            )

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

            results.append({"sender": sender, "subject": subject, "body": body.strip()})
        mail.logout()
    except Exception as e:
        log.error(f"[email] Fetch error: {e}")
    return results

def email_loop():
    cfg = CONFIG["email"]
    interval = cfg.get("check_interval_seconds", 15)
    log.info(f"[email] Watching {cfg['address']} every {interval}s")

    while True:
        try:
            for msg in fetch_unread_emails():
                text = msg["body"] or msg["subject"]
                identity = f"email:{msg['sender']}"
                log.info(f"[email] {msg['sender']}: {text[:60]}")

                reply, file_path = handle_command(text, identity)
                send_email(
                    to_addr=msg["sender"],
                    subject=f"Re: {msg['subject']}",
                    body=reply,
                    attachment_path=file_path,
                )
        except Exception as e:
            log.error(f"[email] Loop error: {e}")
        time.sleep(interval)

# ── Telegram Channel ──────────────────────────────────────────────────────────

def telegram_loop():
    from telegram import Update
    from telegram.ext import Application, MessageHandler, filters, ContextTypes
    import asyncio

    cfg = CONFIG["telegram"]
    allowed_ids: list[int] = cfg.get("allowed_user_ids", [])

    async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id

        # ── Authorization: only allowed Telegram user IDs ────────────────
        if not security.verify_telegram_user(user_id, allowed_ids):
            await update.message.reply_text("Unauthorized.")
            return

        text = update.message.text or ""
        identity = f"telegram:{user_id}"
        log.info(f"[telegram] {user_id}: {text[:60]}")

        reply, file_path = handle_command(text, identity)

        if file_path and os.path.exists(file_path):
            if file_path.endswith(".png"):
                with open(file_path, "rb") as f:
                    await update.message.reply_photo(photo=f, caption=reply[:1024])
            elif file_path.endswith(".mp4"):
                with open(file_path, "rb") as f:
                    await update.message.reply_video(video=f, caption=reply[:1024])
            os.remove(file_path)
        else:
            # Telegram messages max 4096 chars — split if needed
            for chunk in [reply[i:i+4000] for i in range(0, len(reply), 4000)]:
                await update.message.reply_text(chunk)

    async def run():
        app = Application.builder().token(cfg["bot_token"]).build()
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
        log.info("[telegram] Bot started")
        await app.run_polling()

    asyncio.run(run())

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    wa_cfg = CONFIG.get("whatsapp", {})
    im_cfg = CONFIG.get("imessage", {})

    print("=" * 56)
    print("  PyBridge — Secure AI Remote Control")
    print(f"  OS            : {OS}")
    print(f"  Default model : {current_model}")
    print(f"  Fallback      : {' → '.join(CONFIG.get('fallback_chain', []))}")
    print(f"  Email         : {CONFIG['email']['enabled']}")
    print(f"  Telegram      : {CONFIG['telegram']['enabled']}")
    print(f"  WhatsApp      : {wa_cfg.get('enabled', False)}")
    print(f"  iMessage      : {im_cfg.get('enabled', False)}{' (macOS only)' if OS != 'Darwin' else ''}")
    print(f"  Security      : rate-limit + injection-block + auth")
    print("=" * 56)

    # Wire alert callbacks so log_watcher and scheduler can push to phone
    def _broadcast_alert(msg: str):
        """Send a proactive alert to all enabled channels."""
        try:
            if CONFIG["email"]["enabled"]:
                send_email(
                    to_addr=CONFIG["email"]["allowed_senders"][0],
                    subject="[PyBridge Alert]",
                    body=msg,
                )
        except Exception as e:
            log.error(f"Alert delivery failed: {e}")

    log_watcher.set_alert_fn(_broadcast_alert)
    scheduler.set_deliver_fn(_broadcast_alert)

    threads = []

    if CONFIG["email"]["enabled"]:
        t = threading.Thread(target=email_loop, daemon=True, name="email")
        t.start()
        threads.append(t)

    if CONFIG["telegram"]["enabled"]:
        t = threading.Thread(target=telegram_loop, daemon=True, name="telegram")
        t.start()
        threads.append(t)

    if wa_cfg.get("enabled", False):
        bridge_dir = os.path.join(BASE_DIR, "whatsapp_bridge")
        t = threading.Thread(
            target=wa_channel.whatsapp_loop,
            args=(CONFIG, handle_command, bridge_dir),
            daemon=True, name="whatsapp"
        )
        t.start()
        threads.append(t)

    if im_cfg.get("enabled", False):
        if OS != "Darwin":
            log.warning("iMessage is only supported on macOS. Skipping.")
        else:
            t = threading.Thread(
                target=im_channel.imessage_loop,
                args=(CONFIG, handle_command),
                daemon=True, name="imessage"
            )
            t.start()
            threads.append(t)

    if not threads:
        print("\nNo channels enabled. Edit config.json and set at least one channel to enabled: true")
        sys.exit(1)

    print("\nRunning. Waiting for messages from your phone...\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        screen.stop_stream()
        print("\nStopped.")
