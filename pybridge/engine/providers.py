from __future__ import annotations
"""
engine/providers.py
Multi-provider abstraction: Anthropic, OpenAI, Ollama.
Each provider normalises requests and responses into a common format.
"""

import json
import time
import logging
import urllib.request
import urllib.error
from typing import Any

log = logging.getLogger("pybridge.engine.providers")

# ── Common response shape ─────────────────────────────────────────────────────

def _resp(text: str, tool_calls: list, stop_reason: str, usage: dict) -> dict:
    return {
        "text": text,
        "tool_calls": tool_calls,   # list of {id, name, arguments (str)}
        "stop_reason": stop_reason, # "end_turn" | "tool_calls" | "max_tokens"
        "usage": usage,             # {input, output, total}
    }

# ── Error classifier ──────────────────────────────────────────────────────────

def classify_error(err: str) -> str:
    e = err.lower()
    if any(x in e for x in ["invalid api key", "authentication", "unauthorized", "401"]):
        return "auth"
    if any(x in e for x in ["billing", "payment", "quota exceeded", "insufficient_quota"]):
        return "billing"
    if any(x in e for x in ["rate limit", "429", "too many requests"]):
        return "rate_limit"
    if any(x in e for x in ["overloaded", "503", "529", "capacity"]):
        return "overloaded"
    if any(x in e for x in ["context length", "context window", "token limit", "maximum context"]):
        return "context_overflow"
    if any(x in e for x in ["timeout", "timed out", "read timeout"]):
        return "timeout"
    return "unknown"

# ── HTTP helper ───────────────────────────────────────────────────────────────

def _http_post(url: str, payload: dict, headers: dict, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {e.code}: {body[:400]}")

# ── Anthropic ─────────────────────────────────────────────────────────────────

def call_anthropic(messages: list, model: str, api_key: str,
                   system: str = "", tools: list = None,
                   max_tokens: int = 4096, timeout: int = 120) -> dict:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = [_anthropic_tool(t) for t in tools]

    raw = _http_post(url, payload, headers, timeout)

    text = ""
    tool_calls = []
    for block in raw.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")
        elif block.get("type") == "tool_use":
            tool_calls.append({
                "id": block["id"],
                "name": block["name"],
                "arguments": json.dumps(block.get("input", {})),
            })

    stop = raw.get("stop_reason", "end_turn")
    if tool_calls and stop == "tool_use":
        stop = "tool_calls"

    usage_raw = raw.get("usage", {})
    usage = {
        "input": usage_raw.get("input_tokens", 0),
        "output": usage_raw.get("output_tokens", 0),
        "total": usage_raw.get("input_tokens", 0) + usage_raw.get("output_tokens", 0),
    }
    return _resp(text, tool_calls, stop, usage)


def _anthropic_tool(t: dict) -> dict:
    return {
        "name": t["name"],
        "description": t.get("description", ""),
        "input_schema": {
            "type": "object",
            "properties": t.get("parameters", {}).get("properties", {}),
            "required": t.get("parameters", {}).get("required", []),
        },
    }

# ── OpenAI / Codex ────────────────────────────────────────────────────────────

def call_openai(messages: list, model: str, api_key: str,
                system: str = "", tools: list = None,
                max_tokens: int = 4096, base_url: str = "",
                timeout: int = 120) -> dict:
    url = (base_url.rstrip("/") + "/chat/completions") if base_url else "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    full_messages = []
    if system:
        full_messages.append({"role": "system", "content": system})
    full_messages.extend(messages)

    payload: dict[str, Any] = {
        "model": model,
        "messages": full_messages,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = [_openai_tool(t) for t in tools]
        payload["tool_choice"] = "auto"

    raw = _http_post(url, payload, headers, timeout)
    choice = raw.get("choices", [{}])[0]
    msg = choice.get("message", {})

    text = msg.get("content") or ""
    tool_calls = []
    for tc in msg.get("tool_calls") or []:
        tool_calls.append({
            "id": tc["id"],
            "name": tc["function"]["name"],
            "arguments": tc["function"].get("arguments", "{}"),
        })

    stop = "tool_calls" if tool_calls else "end_turn"
    if choice.get("finish_reason") == "length":
        stop = "max_tokens"

    usage_raw = raw.get("usage", {})
    usage = {
        "input": usage_raw.get("prompt_tokens", 0),
        "output": usage_raw.get("completion_tokens", 0),
        "total": usage_raw.get("total_tokens", 0),
    }
    return _resp(text, tool_calls, stop, usage)


def _openai_tool(t: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t.get("description", ""),
            "parameters": {
                "type": "object",
                "properties": t.get("parameters", {}).get("properties", {}),
                "required": t.get("parameters", {}).get("required", []),
            },
        },
    }

# ── Ollama (local) ────────────────────────────────────────────────────────────

def call_ollama(messages: list, model: str, system: str = "",
                base_url: str = "http://localhost:11434",
                max_tokens: int = 4096, timeout: int = 120) -> dict:
    url = base_url.rstrip("/") + "/api/chat"
    headers = {"Content-Type": "application/json"}

    full_messages = []
    if system:
        full_messages.append({"role": "system", "content": system})
    full_messages.extend(messages)

    payload = {
        "model": model,
        "messages": full_messages,
        "stream": False,
        "options": {"num_predict": max_tokens},
    }

    raw = _http_post(url, payload, headers, timeout)
    msg = raw.get("message", {})
    text = msg.get("content", "")

    usage = {
        "input": raw.get("prompt_eval_count", 0),
        "output": raw.get("eval_count", 0),
        "total": raw.get("prompt_eval_count", 0) + raw.get("eval_count", 0),
    }
    return _resp(text, [], "end_turn", usage)


def list_ollama_models(base_url: str = "http://localhost:11434") -> list[str]:
    try:
        req = urllib.request.Request(base_url.rstrip("/") + "/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []

# ── OpenCode (via REST API) ───────────────────────────────────────────────────

def call_opencode(prompt: str, messages: list, model: str,
                  base_url: str = "http://localhost:54321",
                  max_tokens: int = 4096, timeout: int = 120) -> dict:
    url = base_url.rstrip("/") + "/v1/chat/completions"
    headers = {"Content-Type": "application/json"}

    full_messages = [{"role": "user", "content": prompt}]
    if messages:
        full_messages = messages + full_messages

    payload = {
        "model": model,
        "messages": full_messages,
        "max_tokens": max_tokens,
    }

    try:
        raw = _http_post(url, payload, headers, timeout)
        choice = raw.get("choices", [{}])[0]
        msg = choice.get("message", {})
        text = msg.get("content", "")

        usage_raw = raw.get("usage", {})
        usage = {
            "input": usage_raw.get("prompt_tokens", 0),
            "output": usage_raw.get("completion_tokens", 0),
            "total": usage_raw.get("total_tokens", 0),
        }
        return _resp(text, [], "end_turn", usage)
    except Exception as e:
        raise RuntimeError(f"OpenCode API error: {e}")


def opencode_sessions(base_url: str = "http://localhost:54321") -> list[dict]:
    try:
        req = urllib.request.Request(base_url.rstrip("/") + "/session")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("data", []) if isinstance(data, dict) else data
    except Exception as e:
        log.warning(f"Failed to list OpenCode sessions: {e}")
        return []


def opencode_create_session(base_url: str = "http://localhost:54321",
                           project_path: str = "") -> dict | None:
    try:
        url = base_url.rstrip("/") + "/session"
        payload = {}
        if project_path:
            payload["project_path"] = project_path
        headers = {"Content-Type": "application/json"}
        raw = _http_post(url, payload, headers, timeout=30)
        return raw if raw else None
    except Exception as e:
        log.warning(f"Failed to create OpenCode session: {e}")
        return None


def opencode_send_message(session_id: str, prompt: str,
                         base_url: str = "http://localhost:54321",
                         timeout: int = 120) -> dict:
    url = base_url.rstrip("/") + f"/session/{session_id}/message"
    headers = {"Content-Type": "application/json"}
    payload = {"prompt": prompt}

    data = _http_post(url, payload, headers, timeout)
    return data


def opencode_health(base_url: str = "http://localhost:54321") -> bool:
    try:
        req = urllib.request.Request(base_url.rstrip("/") + "/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False

# ── Google Gemini ────────────────────────────────────────────────────────────────

def call_gemini(messages: list, model: str, api_key: str,
                system: str = "", max_tokens: int = 4096,
                timeout: int = 120) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}

    full_contents = []
    if system:
        full_contents.append({"role": "user", "parts": [{"text": system}]})
    for msg in messages:
        full_contents.append({"role": msg["role"], "parts": [{"text": msg["content"]}]})

    payload = {
        "contents": full_contents,
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.7,
        }
    }

    raw = _http_post(url, payload, headers, timeout)
    
    text = ""
    if "candidates" in raw and raw["candidates"]:
        candidate = raw["candidates"][0]
        if "content" in candidate and "parts" in candidate["content"]:
            for part in candidate["content"]["parts"]:
                text += part.get("text", "")

    usage_raw = raw.get("usageMetadata", {})
    usage = {
        "input": usage_raw.get("promptTokenCount", 0),
        "output": usage_raw.get("candidatesTokenCount", 0),
        "total": usage_raw.get("totalTokenCount", 0),
    }
    return _resp(text, [], "end_turn", usage)

# ── Groq ─────────────────────────────────────────────────────────────────────────

def call_groq(messages: list, model: str, api_key: str,
              system: str = "", tools: list = None,
              max_tokens: int = 4096, timeout: int = 120) -> dict:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    full_messages = []
    if system:
        full_messages.append({"role": "system", "content": system})
    full_messages.extend(messages)

    payload = {
        "model": model,
        "messages": full_messages,
        "max_tokens": max_tokens,
    }

    raw = _http_post(url, payload, headers, timeout)
    choice = raw.get("choices", [{}])[0]
    msg = choice.get("message", {})
    text = msg.get("content", "")

    usage_raw = raw.get("usage", {})
    usage = {
        "input": usage_raw.get("prompt_tokens", 0),
        "output": usage_raw.get("completion_tokens", 0),
        "total": usage_raw.get("total_tokens", 0),
    }
    return _resp(text, [], "end_turn", usage)

# ── Mistral ────────────────────────────────────────────────────────────────────

def call_mistral(messages: list, model: str, api_key: str,
                 system: str = "", max_tokens: int = 4096,
                 timeout: int = 120) -> dict:
    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    full_messages = []
    if system:
        full_messages.append({"role": "system", "content": system})
    full_messages.extend(messages)

    payload = {
        "model": model,
        "messages": full_messages,
        "max_tokens": max_tokens,
    }

    raw = _http_post(url, payload, headers, timeout)
    choice = raw.get("choices", [{}])[0]
    msg = choice.get("message", {})
    text = msg.get("content", "")

    usage_raw = raw.get("usage", {})
    usage = {
        "input": usage_raw.get("prompt_tokens", 0),
        "output": usage_raw.get("completion_tokens", 0),
        "total": usage_raw.get("total_tokens", 0),
    }
    return _resp(text, [], "end_turn", usage)
