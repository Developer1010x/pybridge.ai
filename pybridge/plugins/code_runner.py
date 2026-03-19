"""
plugins/code_runner.py — Run code snippets in any language.

Commands:
  py print("hello")           → run Python
  node console.log(1+1)       → run Node.js
  bash echo $HOME             → run bash
  sh ls -la                   → run sh
  ruby puts "hello"           → run Ruby
  go run: fmt.Println("hi")   → run Go snippet
  sql SELECT 1+1              → run SQLite query
  http GET https://example.com → make HTTP request
"""

import os
import sys
import shutil
import subprocess
import tempfile
import logging
import platform

log = logging.getLogger("pybridge.coderunner")
OS = platform.system()

TIMEOUT = 15  # seconds


def _run_code(cmd: list[str], input_data: str = None, timeout: int = TIMEOUT) -> str:
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            input=input_data
        )
        out = r.stdout.strip()
        err = r.stderr.strip()
        result = out
        if err:
            result += (f"\n[stderr]\n{err}" if out else err)
        return result[:3000] or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s"
    except FileNotFoundError as e:
        return f"Runtime not found: {e}"
    except Exception as e:
        return f"Error: {e}"


def _write_temp(code: str, suffix: str) -> str:
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
    f.write(code)
    f.close()
    return f.name


def run_python(code: str) -> str:
    py = shutil.which("python3") or shutil.which("python")
    if not py:
        return "Python not found."
    path = _write_temp(code, ".py")
    try:
        return _run_code([py, path])
    finally:
        os.unlink(path)


def run_node(code: str) -> str:
    node = shutil.which("node") or shutil.which("nodejs")
    if not node:
        return "Node.js not found."
    path = _write_temp(code, ".js")
    try:
        return _run_code([node, path])
    finally:
        os.unlink(path)


def run_bash(code: str) -> str:
    shell = shutil.which("bash") or shutil.which("sh")
    if not shell:
        return "bash/sh not found."
    return _run_code([shell, "-c", code])


def run_ruby(code: str) -> str:
    ruby = shutil.which("ruby")
    if not ruby:
        return "Ruby not found."
    path = _write_temp(code, ".rb")
    try:
        return _run_code([ruby, path])
    finally:
        os.unlink(path)


def run_go(code: str) -> str:
    go = shutil.which("go")
    if not go:
        return "Go not found."
    # Wrap in a main package if not already
    if "package main" not in code:
        code = f'package main\nimport "fmt"\nfunc main() {{\n{code}\n}}'
    path = _write_temp(code, ".go")
    try:
        return _run_code([go, "run", path], timeout=30)
    finally:
        os.unlink(path)


def run_sql(query: str) -> str:
    sqlite = shutil.which("sqlite3")
    if not sqlite:
        # Try via Python's built-in sqlite3
        try:
            import sqlite3
            conn = sqlite3.connect(":memory:")
            cur = conn.execute(query)
            rows = cur.fetchall()
            if not rows:
                return "(no rows)"
            return "\n".join(str(r) for r in rows[:100])
        except Exception as e:
            return f"SQL error: {e}"
    return _run_code([sqlite3, ":memory:", query])


def run_http(method: str, url: str, body: str = "") -> str:
    try:
        import urllib.request
        import urllib.error
        import json as jsonlib

        method = method.upper()
        data = body.encode() if body else None

        if not url.startswith("http"):
            return "URL must start with http:// or https://"

        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("User-Agent", "PyBridge/1.0")
        if body:
            req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            status = resp.status
            # Try to pretty-print JSON
            try:
                parsed = jsonlib.loads(raw)
                raw = jsonlib.dumps(parsed, indent=2)
            except Exception:
                pass
            return f"HTTP {status}\n\n{raw[:2000]}"

    except urllib.error.HTTPError as e:
        body_err = e.read().decode("utf-8", errors="ignore")[:500]
        return f"HTTP {e.code} {e.reason}\n{body_err}"
    except Exception as e:
        return f"Request failed: {e}"


def handle(cmd: str, args: str) -> str:
    code = args.strip()

    if not code:
        return f"Usage: {cmd} <code>"

    if cmd == "py":
        return run_python(code)

    if cmd == "node":
        return run_node(code)

    if cmd in ("bash", "sh"):
        return run_bash(code)

    if cmd == "ruby":
        return run_ruby(code)

    if cmd == "go":
        return run_go(code)

    if cmd == "sql":
        return run_sql(code)

    if cmd == "http":
        # "http GET https://example.com [body]"
        parts = code.split(None, 2)
        method = parts[0] if parts else "GET"
        url = parts[1] if len(parts) > 1 else ""
        body = parts[2] if len(parts) > 2 else ""
        if not url:
            return "Usage: http <METHOD> <URL> [body]"
        return run_http(method, url, body)

    if cmd == "get":
        return run_http("GET", code)

    if cmd == "post":
        parts = code.split(None, 1)
        url = parts[0]
        body = parts[1] if len(parts) > 1 else ""
        return run_http("POST", url, body)

    return f"Unknown runner: {cmd}"
