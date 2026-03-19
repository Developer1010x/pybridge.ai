"""
plugins/vscode.py — VS Code integration.

Commands:
  vscode open src/main.py     → open file in VS Code
  vscode open .               → open current folder
  vscode run <task>           → run a VS Code task
  vscode ext list             → list installed extensions
  vscode ext install <ext>    → install extension
  vscode diff file1 file2     → open diff in VS Code
"""

import os
import shutil
import subprocess
import logging

log = logging.getLogger("pybridge.vscode")


def _code(args: list[str], timeout: int = 10) -> str:
    code = shutil.which("code") or shutil.which("code-insiders")
    if not code:
        return (
            "VS Code CLI not found.\n"
            "Enable it: VS Code → Command Palette → 'Shell Command: Install code in PATH'"
        )
    try:
        r = subprocess.run([code] + args, capture_output=True, text=True, timeout=timeout)
        out = r.stdout.strip() or r.stderr.strip()
        return out or "Done."
    except subprocess.TimeoutExpired:
        return "VS Code command timed out"
    except Exception as e:
        return f"VS Code error: {e}"


def open_file(path: str) -> str:
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return f"Path not found: {path}"
    return _code([path])


def run_task(task_name: str) -> str:
    return _code(["--command", f"workbench.action.tasks.runTask", task_name])


def list_extensions() -> str:
    return _code(["--list-extensions", "--show-versions"])


def install_extension(ext_id: str) -> str:
    return _code(["--install-extension", ext_id], timeout=60)


def diff_files(file1: str, file2: str) -> str:
    f1 = os.path.expanduser(file1)
    f2 = os.path.expanduser(file2)
    if not os.path.exists(f1):
        return f"File not found: {f1}"
    if not os.path.exists(f2):
        return f"File not found: {f2}"
    return _code(["--diff", f1, f2])


def handle(cmd: str, args: str) -> str:
    parts = args.strip().split(None, 1)
    sub = parts[0] if parts else ""
    rest = parts[1] if len(parts) > 1 else ""

    if cmd == "vscode":
        if sub == "open":
            path = rest or "."
            return open_file(path)
        if sub == "run":
            if not rest:
                return "Usage: vscode run <task name>"
            return run_task(rest)
        if sub in ("ext", "extensions"):
            if rest.startswith("list"):
                return list_extensions()
            if rest.startswith("install"):
                ext = rest[7:].strip()
                return install_extension(ext) if ext else "Usage: vscode ext install <extension-id>"
            return list_extensions()
        if sub == "diff":
            files = rest.split()
            if len(files) < 2:
                return "Usage: vscode diff <file1> <file2>"
            return diff_files(files[0], files[1])
        # Default: open path or current dir
        return open_file(sub or ".")

    return f"Unknown vscode command: {cmd}"
