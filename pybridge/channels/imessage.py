"""
channels/imessage.py — iMessage channel for PyBridge. macOS only.

Receive: Polls ~/Library/Messages/chat.db (SQLite) for new messages.
Send:    Uses AppleScript via osascript.

Requirements:
  - macOS only
  - Grant "Full Disk Access" to Terminal (or your Python process) in:
    System Settings → Privacy & Security → Full Disk Access
  - iMessage must be signed in on this Mac
"""

import os
import sys
import time
import sqlite3
import logging
import subprocess
import platform
import shutil

log = logging.getLogger("pybridge.imessage")

# Path to Messages SQLite database
DB_PATH = os.path.expanduser("~/Library/Messages/chat.db")

# Track last seen message ROWID so we don't re-process old ones
_last_rowid: int = 0


# ── Check ─────────────────────────────────────────────────────────────────────

def is_available() -> bool:
    """Check if iMessage is usable on this machine."""
    if platform.system() != "Darwin":
        return False
    if not os.path.exists(DB_PATH):
        log.warning(f"[imessage] chat.db not found at {DB_PATH}")
        return False
    if not shutil.which("osascript"):
        log.warning("[imessage] osascript not found")
        return False
    return True


def check_db_access() -> bool:
    """Try reading the DB — fails if Full Disk Access not granted."""
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.execute("SELECT COUNT(*) FROM message").fetchone()
        conn.close()
        return True
    except Exception as e:
        log.error(
            f"[imessage] Cannot read chat.db: {e}\n"
            "Fix: System Settings → Privacy & Security → Full Disk Access → add Terminal"
        )
        return False


# ── Receive ───────────────────────────────────────────────────────────────────

def _get_new_messages(allowed_handles: list[str]) -> list[dict]:
    """
    Poll chat.db for new incoming messages since _last_rowid.
    Returns list of {handle, text, rowid}.
    """
    global _last_rowid

    results = []
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        # Get new incoming messages (is_from_me = 0)
        rows = conn.execute(
            """
            SELECT
                m.ROWID,
                m.text,
                h.id AS handle
            FROM message m
            JOIN handle h ON m.handle_id = h.ROWID
            WHERE m.ROWID > ?
              AND m.is_from_me = 0
              AND m.text IS NOT NULL
              AND m.text != ''
            ORDER BY m.ROWID ASC
            """,
            (int(_last_rowid),),
        ).fetchall()

        conn.close()

        for row in rows:
            rowid  = row["ROWID"]
            handle = row["handle"]   # e.g. "+919876543210" or "someone@email.com"
            text   = row["text"].strip()

            # Update last seen
            if rowid > _last_rowid:
                _last_rowid = rowid

            # Authorization: skip if not in allowed list
            if allowed_handles:
                normalized_allowed = [h.strip().lower() for h in allowed_handles]
                if handle.strip().lower() not in normalized_allowed:
                    log.warning(f"[imessage] Blocked message from {handle}")
                    continue

            if text:
                results.append({"handle": handle, "text": text, "rowid": rowid})

    except Exception as e:
        log.error(f"[imessage] DB read error: {e}")

    return results


def _init_last_rowid():
    """Set _last_rowid to current max so we only see NEW messages after startup."""
    global _last_rowid
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        row = conn.execute("SELECT MAX(ROWID) FROM message").fetchone()
        conn.close()
        _last_rowid = row[0] or 0
        log.info(f"[imessage] Starting from message ROWID {_last_rowid}")
    except Exception as e:
        log.error(f"[imessage] Could not init ROWID: {e}")


# ── Send ──────────────────────────────────────────────────────────────────────

def _escape_applescript(s: str) -> str:
    """Escape a string for safe embedding in AppleScript double quotes."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def send_message(handle: str, text: str):
    """Send an iMessage or SMS via AppleScript."""
    safe_text = _escape_applescript(text)
    safe_handle = _escape_applescript(handle)

    script = f'''
    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy "{safe_handle}" of targetService
        send "{safe_text}" to targetBuddy
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            log.error(f"[imessage] Send error: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        log.error("[imessage] Send timed out")
    except Exception as e:
        log.error(f"[imessage] Send failed: {e}")


def send_image(handle: str, image_path: str, caption: str):
    """Send an image via iMessage using AppleScript."""
    abs_path = os.path.abspath(image_path)
    safe_path = _escape_applescript(abs_path)
    safe_handle = _escape_applescript(handle)

    script = f'''
    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy "{safe_handle}" of targetService
        send (POSIX file "{safe_path}") to targetBuddy
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            log.error(f"[imessage] Send image error: {result.stderr[:200]}")
            # Fallback: send caption as text
            if caption:
                send_message(handle, caption)
        elif caption:
            send_message(handle, caption)

        if os.path.exists(image_path):
            os.remove(image_path)

    except Exception as e:
        log.error(f"[imessage] Send image failed: {e}")


# ── Loop ──────────────────────────────────────────────────────────────────────

def imessage_loop(config: dict, handle_command_fn):
    """
    Main iMessage loop.
    Polls chat.db for new messages, routes through handle_command_fn, replies.
    """
    if not is_available():
        log.error("[imessage] iMessage not available on this system.")
        return

    if not check_db_access():
        log.error(
            "[imessage] No database access.\n"
            "Go to: System Settings → Privacy & Security → Full Disk Access\n"
            "Add Terminal (or your Python executable) to the list."
        )
        return

    im_cfg = config.get("imessage", {})
    allowed = im_cfg.get("allowed_handles", [])   # e.g. ["+919876543210"]
    interval = im_cfg.get("check_interval_seconds", 3)

    _init_last_rowid()
    log.info(f"[imessage] Watching chat.db every {interval}s")

    while True:
        try:
            messages = _get_new_messages(allowed)
            for msg in messages:
                handle = msg["handle"]
                text   = msg["text"]
                identity = f"imessage:{handle}"

                log.info(f"[imessage] {handle}: {text[:60]}")

                reply, file_path = handle_command_fn(text, identity)

                if file_path and os.path.exists(file_path):
                    if file_path.endswith(".png"):
                        send_image(handle, file_path, reply[:200])
                    elif file_path.endswith(".mp4"):
                        # iMessage video via AppleScript
                        send_image(handle, file_path, "")
                        if reply:
                            send_message(handle, reply[:500])
                else:
                    # Split long replies
                    for chunk in [reply[i:i+2000] for i in range(0, len(reply), 2000)]:
                        send_message(handle, chunk)

        except Exception as e:
            log.error(f"[imessage] Loop error: {e}")

        time.sleep(interval)
