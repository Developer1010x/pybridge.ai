#!/usr/bin/env python3
"""
Live smoke test — drives the real router against this machine.

This is NOT the unit suite. It has real side effects: it shells out to git,
docker and npm, and (with --with-screenshot) actually grabs your screen. The
hermetic tests live in ../tests and need none of that:

    python3 -m unittest discover -s tests -v

Usage:
    python3 test_run.py                    # no screenshot
    python3 test_run.py --with-screenshot  # include screen capture
"""

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import warnings
warnings.filterwarnings("ignore")

import main   # noqa: E402

WITH_SCREENSHOT = "--with-screenshot" in sys.argv

# (command, substring the reply must contain, required binary or None)
CHECKS = [
    ("help",                 "PyBridge on",       None),
    ("status",               "PyBridge status",   None),
    ("os",                   "Running on",        None),
    ("models",               "Available models",  None),
    ("model",                "Current:",          None),
    ("py print('hello')",    "hello",             "python3"),
    ("sql SELECT 1+1",       "2",                 None),
    ("node console.log(41+1)", "42",              "node"),
    ("bash echo smoke-ok",   "smoke-ok",          "bash"),
    ("tree .",               "main.py",           None),
    ("read config.json 3",   "config.json (lines", None),
    ("git status",           "",                  "git"),
    ("docker ps",            "",                  "docker"),
    ("ps",                   "",                  None),
    ("disk",                 "",                  None),
    ("mem",                  "",                  None),
    ("cpu",                  "",                  None),
    ("ping 127.0.0.1",       "127.0.0.1",         "ping"),
    ("dns localhost",        "localhost",         None),
    ("localip",              ".",                 None),
    ("use claude",           "Switched to claude", None),
    ("use ollama",           "Switched to ollama", None),
    ("find me a good restaurant", None,           None),   # must reach the AI
]

if WITH_SCREENSHOT:
    CHECKS.append(("screenshot", "Screenshot", None))

passed = failed = skipped = 0
identity = "test:smoke"

# The gate allows 20 messages/minute per identity — real protection for a phone,
# but this script fires every check back to back from one identity.
main.SEC["rate_limit_per_minute"] = len(CHECKS) * 2

print("\n" + "=" * 64)
print("  PyBridge live smoke test — real commands, real side effects")
print("=" * 64)

for cmd, expected, needs in CHECKS:
    if needs and not shutil.which(needs):
        print(f"  SKIP  [{cmd:<28}] {needs} not installed")
        skipped += 1
        continue
    try:
        reply, _ = main.handle_command(cmd, identity)
    except Exception as e:
        print(f"  FAIL  [{cmd:<28}] raised {type(e).__name__}: {e}")
        failed += 1
        continue

    text = str(reply)
    snippet = text[:60].replace("\n", " ")

    if expected is None:
        # No assertion available (the AI reply is nondeterministic, and this
        # machine may have no model running) — only a crash is a failure.
        print(f"  OK    [{cmd:<28}] {snippet}")
        passed += 1
    elif expected and expected not in text:
        print(f"  FAIL  [{cmd:<28}] expected {expected!r}, got: {snippet}")
        failed += 1
    elif text.startswith(("Error:", "Blocked:")):
        print(f"  FAIL  [{cmd:<28}] {snippet}")
        failed += 1
    else:
        print(f"  PASS  [{cmd:<28}] {snippet}")
        passed += 1

print("=" * 64)
print(f"  {passed} passed, {failed} failed, {skipped} skipped")
print("=" * 64 + "\n")

sys.exit(0 if failed == 0 else 1)
