from __future__ import annotations
"""
engine/_direct.py
Direct API calls to OpenAI / Ollama used as fallback when the Agent SDK
is unavailable or when the selected model is non-Anthropic.
"""

import time
import logging
import random

from .providers import (
    call_openai, call_ollama, call_opencode,
    call_gemini, call_groq, call_mistral,
    list_ollama_models, classify_error,
)
from .session import SessionManager

log = logging.getLogger("pybridge.engine.direct")

MAX_TOOL_LOOPS = 10
MAX_RETRIES    = 5
BACKOFF_BASE   = 1.5
BACKOFF_CAP    = 30.0

_cooldowns: dict[str, float] = {}


def _in_cooldown(key: str) -> bool:
    return time.time() < _cooldowns.get(key, 0)


def _set_cooldown(key: str, seconds: float = 60.0):
    _cooldowns[key] = time.time() + seconds


def _backoff(attempt: int) -> float:
    delay = min(BACKOFF_BASE ** attempt, BACKOFF_CAP)
    return delay + random.uniform(0, delay * 0.2)


def _new_usage() -> dict:
    return {"input": 0, "output": 0, "total": 0}


def _merge_usage(acc: dict, usage: dict):
    acc["input"]  += usage.get("input", 0)
    acc["output"] += usage.get("output", 0)
    acc["total"]  += usage.get("total", 0)


def _call(cfg: dict, candidate: dict, messages: list, system: str, tools) -> dict:
    p   = candidate["provider"]
    m   = candidate["model"]
    key = candidate["api_key"]
    url = candidate.get("base_url", "")

    if p == "openai":
        return call_openai(messages, m, key, system, tools, base_url=url)
    elif p == "ollama":
        return call_ollama(messages, m, system,
                           base_url=url or "http://localhost:11434")
    elif p == "opencode":
        return call_opencode("", messages, m, base_url=url or "http://localhost:54321")
    elif p == "gemini":
        return call_gemini(messages, m, key, system)
    elif p == "groq":
        return call_groq(messages, m, key, system, tools)
    elif p == "mistral":
        return call_mistral(messages, m, key, system)
    else:
        return call_openai(messages, m, key, system, tools, base_url=url)


def run_direct(config: dict, sessions: SessionManager,
               prompt: str, identity: str,
               model_name: str, system: str = "") -> dict:

    started  = time.time()
    attempts = []
    usage    = _new_usage()

    # Build candidate list
    models_cfg = config.get("models", {})
    catalog: list[dict] = []
    for name, m in models_cfg.items():
        provider = m.get("provider", name)
        if provider == "ollama":
            base = m.get("base_url", "http://localhost:11434")
            avail = list_ollama_models(base)
            mid   = m.get("model", "llama3")
            if avail and mid not in avail:
                mid = avail[0]
            catalog.append({"name": name, "provider": "ollama",
                             "model": mid, "api_key": "", "base_url": base})
        else:
            catalog.append({"name": name, "provider": provider,
                             "model": m.get("model", ""),
                             "api_key": m.get("api_key", ""),
                             "base_url": m.get("base_url", "")})

    # Ordered fallback chain
    chain: list[dict] = []
    seen: set = set()

    def _add(n):
        c = next((x for x in catalog if x["name"] == n), None)
        if c and n not in seen:
            chain.append(c)
            seen.add(n)

    _add(model_name)
    for fb in config.get("fallback_chain", []):
        _add(fb)
    for c in catalog:
        _add(c["name"])

    # Skip Anthropic models (handled by SDK runner)
    chain = [c for c in chain if c["provider"] != "anthropic"]

    history = sessions.load(identity)
    history = sessions.trim(history)
    history.append({"role": "user", "content": prompt})

    for candidate in chain:
        ckey = f"{candidate['provider']}/{candidate['model']}"
        if _in_cooldown(ckey) and len(chain) > 1:
            attempts.append({"candidate": ckey, "skipped": "cooldown"})
            continue

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                messages  = list(history)
                final_txt = ""
                for _ in range(MAX_TOOL_LOOPS):
                    resp = _call(config, candidate, messages, system, None)
                    _merge_usage(usage, resp["usage"])
                    if resp["stop_reason"] != "tool_calls" or not resp["tool_calls"]:
                        final_txt = resp["text"]
                        break

                sessions.append(identity, "user", prompt)
                sessions.append(identity, "assistant", final_txt)

                return {
                    "text":          final_txt,
                    "model_used":    candidate["model"],
                    "provider_used": candidate["provider"],
                    "usage":         usage,
                    "duration_ms":   int((time.time() - started) * 1000),
                    "attempts":      attempts,
                }

            except Exception as e:
                err_str  = str(e)
                err_type = classify_error(err_str)
                log.warning(f"[{ckey}] attempt {attempt} ({err_type}): {err_str[:120]}")
                attempts.append({"candidate": ckey, "attempt": attempt,
                                  "error": err_type, "detail": err_str[:200]})

                if err_type == "context_overflow":
                    sessions.clear(identity)
                    raise RuntimeError("Context too long — history cleared. Try again.")

                if err_type in ("auth", "billing"):
                    _set_cooldown(ckey, 300)
                    break

                if err_type == "rate_limit":
                    _set_cooldown(ckey, 60)
                    break

                if attempt < MAX_RETRIES:
                    time.sleep(_backoff(attempt))
                else:
                    break

    tried = [a["candidate"] for a in attempts]
    raise RuntimeError(
        f"All models failed: {', '.join(dict.fromkeys(tried))}\n"
        f"Last: {attempts[-1]['detail'] if attempts else 'unknown'}"
    )
