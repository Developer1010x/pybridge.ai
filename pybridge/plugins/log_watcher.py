"""
plugins/log_watcher.py — Watch log files and alert on errors.

Commands:
  watch /var/log/app.log        → start watching a log file
  watch /var/log/app.log ERROR  → watch for specific pattern
  unwatch /var/log/app.log      → stop watching
  watchers                      → list active watchers
  tail /var/log/app.log         → get last 50 lines

Auto-alerts when ERROR / FATAL / Exception / Traceback detected.
"""

import os
import re
import time
import threading
import logging
from collections import defaultdict
from datetime import datetime

log = logging.getLogger("pybridge.logwatcher")

# Active watchers: path → WatcherThread
_watchers: dict[str, threading.Thread] = {}
_watcher_stop: dict[str, threading.Event] = {}

# Alert callback — set by main.py
_alert_fn = None  # callable(message: str)

# Default patterns that trigger an alert
DEFAULT_ALERT_PATTERNS = [
    r"error",
    r"fatal",
    r"exception",
    r"traceback",
    r"panic",
    r"critical",
    r"fail(ed|ure)?",
    r"segfault",
    r"oom",
    r"killed",
]


def set_alert_fn(fn):
    """Register the function to call when an alert fires."""
    global _alert_fn
    _alert_fn = fn


def _alert(message: str):
    if _alert_fn:
        try:
            _alert_fn(f"[LOG ALERT] {message}")
        except Exception as e:
            log.error(f"Alert dispatch failed: {e}")
    else:
        log.warning(f"Alert (no dispatch): {message}")


def _watch_file(path: str, patterns: list[str], stop_event: threading.Event):
    """Tail a file and alert on matching lines."""
    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]

    try:
        with open(path, "r", errors="ignore") as f:
            f.seek(0, 2)  # seek to end
            log.info(f"[logwatcher] Watching: {path}")

            while not stop_event.is_set():
                line = f.readline()
                if not line:
                    time.sleep(0.5)
                    continue

                line = line.rstrip()
                if not line:
                    continue

                for pattern in compiled:
                    if pattern.search(line):
                        ts = datetime.now().strftime("%H:%M:%S")
                        _alert(f"{ts} [{os.path.basename(path)}]\n{line}")
                        break  # one alert per line max

    except FileNotFoundError:
        _alert(f"Log file not found: {path}")
    except Exception as e:
        log.error(f"[logwatcher] Error watching {path}: {e}")


def start_watcher(path: str, patterns: list[str] = None) -> str:
    path = os.path.expanduser(path)

    if not os.path.exists(path):
        return f"File not found: {path}"

    if path in _watchers and _watchers[path].is_alive():
        return f"Already watching: {path}"

    stop_event = threading.Event()
    patterns = patterns or DEFAULT_ALERT_PATTERNS

    t = threading.Thread(
        target=_watch_file,
        args=(path, patterns, stop_event),
        daemon=True,
        name=f"watcher:{os.path.basename(path)}"
    )
    _watchers[path] = t
    _watcher_stop[path] = stop_event
    t.start()

    return f"Watching: {path}\nAlerts on: {', '.join(patterns[:3])}{'...' if len(patterns) > 3 else ''}"


def stop_watcher(path: str) -> str:
    path = os.path.expanduser(path)
    if path not in _watcher_stop:
        return f"Not watching: {path}"
    _watcher_stop[path].set()
    del _watcher_stop[path]
    del _watchers[path]
    return f"Stopped watching: {path}"


def list_watchers() -> str:
    if not _watchers:
        return "No active watchers."
    lines = []
    for path, t in _watchers.items():
        status = "active" if t.is_alive() else "dead"
        lines.append(f"  {status}  {path}")
    return "Active watchers:\n" + "\n".join(lines)


def tail_file(path: str, lines: int = 50) -> str:
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return f"File not found: {path}"
    try:
        with open(path, "r", errors="ignore") as f:
            content = f.readlines()
        tail = content[-lines:]
        return f"Last {len(tail)} lines of {os.path.basename(path)}:\n" + "".join(tail)
    except Exception as e:
        return f"Could not read {path}: {e}"


def handle(cmd: str, args: str) -> str:
    if cmd == "watch":
        parts = args.strip().split()
        if not parts:
            return "Usage: watch <path> [pattern]"
        path = parts[0]
        patterns = parts[1:] if len(parts) > 1 else None
        return start_watcher(path, patterns)

    if cmd == "unwatch":
        path = args.strip()
        if not path:
            return "Usage: unwatch <path>"
        return stop_watcher(path)

    if cmd in ("watchers", "watching"):
        return list_watchers()

    if cmd == "tail":
        parts = args.strip().split()
        path = parts[0] if parts else ""
        n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 50
        if not path:
            return "Usage: tail <path> [lines]"
        return tail_file(path, n)

    return f"Unknown log command: {cmd}"
