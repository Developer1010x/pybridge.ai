"""Quick smoke test — runs without needing real API keys."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

# ── Patch config so gateway calls don't fail during routing tests ──────────
import unittest.mock as mock
import requests as _req

_orig_post = _req.post
_orig_get  = _req.get

def _fake_get(url, **kw):
    if "18789" in url:
        r = mock.Mock()
        r.status_code = 200
        r.json.return_value = {"data": [{"id": "claude-sonnet-4-6"}, {"id": "gpt-4o"}]}
        r.raise_for_status = lambda: None
        return r
    return _orig_get(url, **kw)

def _fake_post(url, **kw):
    if "18789" in url:
        r = mock.Mock()
        r.status_code = 200
        r.json.return_value = {
            "choices": [{"message": {"content": "Hello from mock AI!"}}]
        }
        r.raise_for_status = lambda: None
        return r
    return _orig_post(url, **kw)

_req.get  = _fake_get
_req.post = _fake_post

# ── Now import main ────────────────────────────────────────────────────────
import warnings
warnings.filterwarnings("ignore")

import main

# ── Run tests ──────────────────────────────────────────────────────────────
TESTS = [
    "help",
    "status",
    "os",
    "models",
    "model",
    "screenshot",
    "git status",
    "ps",
    "disk",
    "mem",
    "cpu",
    "docker ps",
    "py print('hello')",
    "tree .",
    "clip",
    "npm check",
    "use claude",
    "use codex",
    "hello world",          # → goes to AI (mocked)
]

passed = 0
failed = 0

print("\n" + "="*55)
print("  PyBridge Smoke Tests")
print("="*55)

for cmd in TESTS:
    try:
        reply, fpath = main.handle_command(cmd, "test:smoke")
        snippet = str(reply)[:70].replace("\n", " ")
        print(f"  PASS  [{cmd:<30}] {snippet}")
        passed += 1
    except Exception as e:
        print(f"  FAIL  [{cmd:<30}] {e}")
        failed += 1

print("="*55)
print(f"  {passed} passed, {failed} failed")
print("="*55 + "\n")

sys.exit(0 if failed == 0 else 1)
