"""
plugins/packages.py — Package management & security audits.

Commands:
  npm check           → outdated npm packages
  npm audit           → security vulnerabilities
  pip check           → outdated pip packages
  pip audit           → pip safety check
  audit               → run both npm + pip audit
  npm install <pkg>   → install npm package
  pip install <pkg>   → install pip package
"""

import shutil
import subprocess
import logging

log = logging.getLogger("pybridge.packages")


def _run(cmd: list[str], timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout.strip() or r.stderr.strip() or "(no output)")[:3000]
    except FileNotFoundError:
        return f"Not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return f"Timed out ({timeout}s)"
    except Exception as e:
        return f"Error: {e}"


# ── npm ───────────────────────────────────────────────────────────────────────

def npm_outdated() -> str:
    if not shutil.which("npm"):
        return "npm not found."
    result = _run(["npm", "outdated"])
    return result if result.strip() else "All packages up to date."


def npm_audit() -> str:
    if not shutil.which("npm"):
        return "npm not found."
    return _run(["npm", "audit", "--audit-level=moderate"])


def npm_install(package: str) -> str:
    if not shutil.which("npm"):
        return "npm not found."
    return _run(["npm", "install", package], timeout=60)


def npm_list() -> str:
    if not shutil.which("npm"):
        return "npm not found."
    return _run(["npm", "list", "--depth=0"])


# ── pip ───────────────────────────────────────────────────────────────────────

def pip_outdated() -> str:
    pip = shutil.which("pip3") or shutil.which("pip")
    if not pip:
        return "pip not found."
    return _run([pip, "list", "--outdated"])


def pip_audit() -> str:
    # Try pip-audit first (best tool)
    if shutil.which("pip-audit"):
        return _run(["pip-audit"], timeout=60)
    # Try safety
    if shutil.which("safety"):
        return _run(["safety", "check"], timeout=30)
    pip = shutil.which("pip3") or shutil.which("pip")
    if pip:
        return _run([pip, "list", "--outdated"]) + "\n\n(Install pip-audit for security scanning: pip install pip-audit)"
    return "pip not found."


def pip_install(package: str) -> str:
    pip = shutil.which("pip3") or shutil.which("pip")
    if not pip:
        return "pip not found."
    return _run([pip, "install", package], timeout=60)


def pip_list() -> str:
    pip = shutil.which("pip3") or shutil.which("pip")
    if not pip:
        return "pip not found."
    return _run([pip, "list"])


# ── Combined audit ────────────────────────────────────────────────────────────

def full_audit() -> str:
    results = []
    if shutil.which("npm"):
        results.append("=== npm audit ===")
        results.append(npm_audit())
    if shutil.which("pip3") or shutil.which("pip"):
        results.append("\n=== pip audit ===")
        results.append(pip_audit())
    if not results:
        return "Neither npm nor pip found."
    return "\n".join(results)


# ── Handler ───────────────────────────────────────────────────────────────────

def handle(cmd: str, args: str) -> str:
    pkg = args.strip()

    if cmd == "npm check":
        return npm_outdated()

    if cmd == "npm audit":
        return npm_audit()

    if cmd == "npm install":
        if not pkg:
            return "Usage: npm install <package>"
        return npm_install(pkg)

    if cmd == "npm list":
        return npm_list()

    if cmd == "pip check":
        return pip_outdated()

    if cmd == "pip audit":
        return pip_audit()

    if cmd == "pip install":
        if not pkg:
            return "Usage: pip install <package>"
        return pip_install(pkg)

    if cmd == "pip list":
        return pip_list()

    if cmd == "audit":
        return full_audit()

    return f"Unknown package command: {cmd}"
