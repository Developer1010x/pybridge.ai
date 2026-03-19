from __future__ import annotations
"""
engine/session.py
JSONL-based conversation session management.
Each identity gets its own session file with full history.
"""

import os
import json
import time
import uuid
import logging
import threading
from pathlib import Path

log = logging.getLogger("pybridge.engine.session")

DEFAULT_MAX_TURNS = 40   # keep last N message pairs in context


class SessionManager:
    def __init__(self, sessions_dir: str):
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, session_id: str) -> Path:
        safe = session_id.replace(":", "_").replace("/", "_")
        return self.sessions_dir / f"{safe}.jsonl"

    # ── Load ──────────────────────────────────────────────────────────────────

    def load(self, session_id: str) -> list[dict]:
        """
        Load message history from JSONL file.
        Returns list of {role, content} dicts ready for LLM API.
        """
        path = self._path(session_id)
        if not path.exists():
            return []

        messages = []
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    role = entry.get("role")
                    if role in ("user", "assistant"):
                        messages.append({
                            "role": role,
                            "content": entry.get("content", ""),
                        })
        except Exception as e:
            log.warning(f"Session load error ({session_id}): {e}")
        return messages

    # ── Save ──────────────────────────────────────────────────────────────────

    def append(self, session_id: str, role: str, content: str):
        """Append a single message to the session file (thread-safe)."""
        path = self._path(session_id)
        entry = {
            "id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "ts": int(time.time() * 1000),
        }
        try:
            with self._lock:
                with open(path, "a") as f:
                    f.write(json.dumps(entry) + "\n")
        except Exception as e:
            log.warning(f"Session append error ({session_id}): {e}")

    # ── Context window trim ───────────────────────────────────────────────────

    def trim(self, messages: list[dict], max_turns: int = DEFAULT_MAX_TURNS) -> list[dict]:
        """
        Keep only the last max_turns message pairs.
        Always keeps an even number (user+assistant pairs) so context is clean.
        """
        if len(messages) <= max_turns * 2:
            return messages
        trimmed = messages[-(max_turns * 2):]
        # Ensure we start with a user message
        while trimmed and trimmed[0]["role"] != "user":
            trimmed = trimmed[1:]
        return trimmed

    # ── Clear ─────────────────────────────────────────────────────────────────

    def clear(self, session_id: str):
        path = self._path(session_id)
        if path.exists():
            path.unlink()

    def list_sessions(self) -> list[str]:
        return [p.stem for p in self.sessions_dir.glob("*.jsonl")]
