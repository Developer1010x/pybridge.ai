from __future__ import annotations
"""
engine/runner.py
Agent runner — uses the Claude Agent SDK as primary engine.
Falls back to direct API calls when the SDK is unavailable.
"""

import asyncio
import logging
import time
from typing import Optional

log = logging.getLogger("pybridge.engine.runner")

# ── Try importing the Agent SDK ───────────────────────────────────────────────

try:
    from claude_agent_sdk import (
        query as sdk_query,
        ClaudeAgentOptions,
        ResultMessage,
        SystemMessage,
    )
    _SDK = True
except ImportError:
    _SDK = False
    log.warning("claude-agent-sdk not installed; using direct API fallback")

from .session import SessionManager

# ── Per-identity SDK session tracking ────────────────────────────────────────

_sdk_sessions: dict[str, str] = {}   # identity → last session_id (for resumption)

# ── Model ID mapping (config name → actual model string) ─────────────────────

_BUILTIN_MODELS = {
    "claude":   "claude-opus-4-6",
    "codex":    "gpt-4o",
    "ollama":   "llama3",
    "opencode": "claude-sonnet-4-20250514",
}


def _resolve_model(config: dict, model_name: str) -> tuple[str, str]:
    """Returns (provider, model_id)."""
    cfg = config.get("models", {}).get(model_name, {})
    provider = cfg.get("provider", "anthropic")
    model_id = cfg.get("model", _BUILTIN_MODELS.get(model_name, "claude-opus-4-6"))
    return provider, model_id


# ── AgentRunner ───────────────────────────────────────────────────────────────

class AgentRunner:
    def __init__(self, config: dict, session_manager: SessionManager):
        self.cfg      = config
        self.sessions = session_manager

        # Build catalog for fallback / list_models()
        self._build_catalog()

    # ── Model catalog ─────────────────────────────────────────────────────────

    def _build_catalog(self):
        models_cfg = self.cfg.get("models", {})
        self._catalog: list[dict] = []
        for name, m in models_cfg.items():
            self._catalog.append({
                "name":     name,
                "provider": m.get("provider", name),
                "model":    m.get("model", ""),
                "api_key":  m.get("api_key", ""),
                "base_url": m.get("base_url", ""),
            })

    def list_models(self) -> str:
        lines = ["Available models:"]
        for c in self._catalog:
            sdk_note = " [SDK]" if (_SDK and c["provider"] == "anthropic") else ""
            lines.append(f"  {c['name']:10} → {c['provider']}/{c['model']}{sdk_note}")
        return "\n".join(lines)

    # ── Main run ──────────────────────────────────────────────────────────────

    def run(self, prompt: str, identity: str, model_name: str,
            system: str = "", **kwargs) -> dict:
        """
        Dispatch to SDK runner (Anthropic models) or direct API (others).
        Returns {text, model_used, provider_used, usage, duration_ms, attempts}.
        """
        provider, model_id = _resolve_model(self.cfg, model_name)

        if _SDK and provider == "anthropic":
            return _run_event_loop(
                self._run_sdk(prompt, identity, model_id, system)
            )
        else:
            return self._run_direct(prompt, identity, model_name, system)

    # ── SDK path ──────────────────────────────────────────────────────────────

    async def _run_sdk(self, prompt: str, identity: str,
                       model_id: str, system: str) -> dict:
        started = time.time()

        sys_prompt = system or (
            "You are PyBridge, a powerful AI assistant running as a daemon on the "
            "user's computer. You have full access to the shell, filesystem, web "
            "search, and web fetch. Be concise and direct. When asked to run "
            "commands, run them and show the output."
        )

        resume_id = _sdk_sessions.get(identity)

        options = ClaudeAgentOptions(
            model=model_id,
            allowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep",
                           "WebSearch", "WebFetch"],
            permission_mode="bypassPermissions",
            system_prompt=sys_prompt,
            max_turns=10,
            **({"resume": resume_id} if resume_id else {}),
        )

        result_text = ""
        new_session_id: Optional[str] = resume_id

        async for message in sdk_query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                result_text = message.result or ""
            elif isinstance(message, SystemMessage) and message.subtype == "init":
                new_session_id = message.data.get("session_id", new_session_id)

        if new_session_id:
            _sdk_sessions[identity] = new_session_id

        return {
            "text":          result_text,
            "model_used":    model_id,
            "provider_used": "anthropic",
            "usage":         {"input": 0, "output": 0, "total": 0},
            "duration_ms":   int((time.time() - started) * 1000),
            "attempts":      [],
        }

    # ── Direct API fallback ───────────────────────────────────────────────────

    def _run_direct(self, prompt: str, identity: str,
                    model_name: str, system: str) -> dict:
        """
        Direct API path used for non-Anthropic models (OpenAI, Ollama)
        or when the Agent SDK is not installed.
        """
        from ._direct import run_direct
        return run_direct(self.cfg, self.sessions, prompt, identity, model_name, system)


# ── Event loop helper ─────────────────────────────────────────────────────────

def _run_event_loop(coro):
    """
    Run an async coroutine from synchronous code.
    Works even when called from a non-main thread.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an already-running loop (rare in this daemon but safe)
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)
