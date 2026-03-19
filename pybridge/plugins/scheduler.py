from __future__ import annotations
"""
plugins/scheduler.py — Schedule recurring & one-shot tasks.

Commands:
  every 30m screenshot              → screenshot every 30 min
  every 1h git status               → run git status every hour
  every 5m tail /var/log/app.log 20 → tail log every 5 min
  at 09:00 run npm test             → run at specific time daily
  at 09:00 screenshot               → screenshot at 9am daily
  crons                             → list scheduled tasks
  cancel <id>                       → cancel a scheduled task
"""

import re
import time
import threading
import logging
from datetime import datetime, timedelta

log = logging.getLogger("pybridge.scheduler")

# task id → {"desc", "interval_s", "next_run", "fn", "stop_event"}
_tasks: dict[str, dict] = {}
_task_counter = 0

# Result callback — sends output to user's phone
_deliver_fn = None  # callable(message: str)


def set_deliver_fn(fn):
    global _deliver_fn
    _deliver_fn = fn


def _deliver(msg: str):
    if _deliver_fn:
        try:
            _deliver_fn(msg)
        except Exception as e:
            log.error(f"Scheduler deliver failed: {e}")
    else:
        log.info(f"[scheduler] (no deliver) {msg[:100]}")


def _parse_interval(text: str) -> int | None:
    """Parse '30m', '1h', '5s', '2d' → seconds."""
    text = text.strip().lower()
    patterns = [
        (r"^(\d+)s$", 1),
        (r"^(\d+)m$", 60),
        (r"^(\d+)h$", 3600),
        (r"^(\d+)d$", 86400),
    ]
    for pattern, multiplier in patterns:
        m = re.match(pattern, text)
        if m:
            return int(m.group(1)) * multiplier
    return None


def _parse_time(text: str) -> datetime | None:
    """Parse 'HH:MM' → next occurrence of that time today or tomorrow."""
    text = text.strip()
    try:
        t = datetime.strptime(text, "%H:%M")
        now = datetime.now()
        target = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target
    except ValueError:
        return None


def _run_task(task_id: str, command_text: str, handle_command_fn, stop_event: threading.Event):
    """Run a task on schedule, deliver result to phone."""
    task = _tasks.get(task_id)
    if not task:
        return

    interval = task["interval_s"]
    at_time = task.get("at_time")

    while not stop_event.is_set():
        now = datetime.now()

        if at_time:
            # One-per-day at specific time
            target = now.replace(
                hour=at_time.hour, minute=at_time.minute, second=0, microsecond=0
            )
            if target <= now:
                target += timedelta(days=1)
            wait = (target - now).total_seconds()
        else:
            wait = interval

        # Sleep in small chunks to catch stop_event quickly
        slept = 0
        while slept < wait and not stop_event.is_set():
            time.sleep(min(5, wait - slept))
            slept += 5

        if stop_event.is_set():
            break

        log.info(f"[scheduler] Running task {task_id}: {command_text}")
        try:
            reply, file_path = handle_command_fn(command_text, f"scheduler:{task_id}")
            ts = datetime.now().strftime("%H:%M:%S")
            _deliver(f"[Scheduled @ {ts}] {task['desc']}\n\n{reply}")
        except Exception as e:
            _deliver(f"[Scheduled task {task_id} error] {e}")


def add_recurring(interval_text: str, command_text: str, handle_command_fn) -> str:
    global _task_counter
    interval_s = _parse_interval(interval_text)
    if not interval_s:
        return f"Could not parse interval: '{interval_text}'. Use 30s, 5m, 1h, 2d."

    _task_counter += 1
    task_id = str(_task_counter)
    stop_event = threading.Event()
    desc = f"every {interval_text}: {command_text}"

    _tasks[task_id] = {
        "id": task_id,
        "desc": desc,
        "interval_s": interval_s,
        "command": command_text,
        "stop_event": stop_event,
        "at_time": None,
    }

    t = threading.Thread(
        target=_run_task,
        args=(task_id, command_text, handle_command_fn, stop_event),
        daemon=True,
        name=f"sched:{task_id}"
    )
    t.start()

    return f"Scheduled (ID {task_id}): {desc}"


def add_at_time(time_text: str, command_text: str, handle_command_fn) -> str:
    global _task_counter
    target = _parse_time(time_text)
    if not target:
        return f"Could not parse time: '{time_text}'. Use HH:MM (e.g. 09:00)."

    _task_counter += 1
    task_id = str(_task_counter)
    stop_event = threading.Event()
    desc = f"daily at {time_text}: {command_text}"

    _tasks[task_id] = {
        "id": task_id,
        "desc": desc,
        "interval_s": 86400,
        "command": command_text,
        "stop_event": stop_event,
        "at_time": target,
    }

    t = threading.Thread(
        target=_run_task,
        args=(task_id, command_text, handle_command_fn, stop_event),
        daemon=True,
        name=f"sched:{task_id}"
    )
    t.start()

    return f"Scheduled (ID {task_id}): {desc}\nFirst run at: {target.strftime('%H:%M on %b %d')}"


def list_tasks() -> str:
    if not _tasks:
        return "No scheduled tasks."
    lines = ["Scheduled tasks:"]
    for tid, task in _tasks.items():
        lines.append(f"  [{tid}] {task['desc']}")
    return "\n".join(lines)


def cancel_task(task_id: str) -> str:
    if task_id not in _tasks:
        return f"Task ID '{task_id}' not found."
    _tasks[task_id]["stop_event"].set()
    desc = _tasks.pop(task_id)["desc"]
    return f"Cancelled: {desc}"


def cancel_all() -> str:
    if not _tasks:
        return "No tasks to cancel."
    count = len(_tasks)
    for task in _tasks.values():
        task["stop_event"].set()
    _tasks.clear()
    return f"Cancelled {count} task(s)."


def handle(cmd: str, args: str, handle_command_fn) -> str:
    parts = args.strip().split(None, 1)

    if cmd == "every":
        # every 30m screenshot
        if len(parts) < 2:
            return "Usage: every <interval> <command>  e.g. every 30m screenshot"
        interval = parts[0]
        command = parts[1]
        return add_recurring(interval, command, handle_command_fn)

    if cmd == "at":
        # at 09:00 run npm test
        if len(parts) < 2:
            return "Usage: at <HH:MM> <command>  e.g. at 09:00 git status"
        time_str = parts[0]
        command = parts[1]
        return add_at_time(time_str, command, handle_command_fn)

    if cmd in ("crons", "scheduled", "tasks", "jobs"):
        return list_tasks()

    if cmd in ("cancel", "unschedule", "remove job"):
        tid = args.strip()
        if tid.lower() == "all":
            return cancel_all()
        return cancel_task(tid)

    return f"Unknown scheduler command: {cmd}"
