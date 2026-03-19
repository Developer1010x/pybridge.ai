"""
plugins/file_ops.py — File & code operations.

Commands:
  read src/main.py            → send file contents
  read src/main.py 1-50       → specific lines
  search "def login"          → grep across codebase
  find *.py                   → find files by pattern
  open src/main.py            → open in VS Code / default editor
  tree                        → directory tree
  tree src/                   → tree of a specific folder
  wc src/main.py              → word/line count
"""

import os
import glob
import shutil
import subprocess
import platform
import fnmatch
import logging
from pathlib import Path

log = logging.getLogger("pybridge.fileops")
OS = platform.system()


def read_file(path: str, lines_range: str = "") -> str:
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return f"File not found: {path}"
    if os.path.isdir(path):
        return f"'{path}' is a directory. Use 'tree {path}' or 'find' instead."
    try:
        with open(path, "r", errors="ignore") as f:
            all_lines = f.readlines()

        total = len(all_lines)

        if lines_range:
            # Support "1-50" or "10"
            if "-" in lines_range:
                start, end = lines_range.split("-", 1)
                start = max(int(start) - 1, 0)
                end = min(int(end), total)
            else:
                start = max(int(lines_range) - 1, 0)
                end = min(start + 50, total)
            selected = all_lines[start:end]
            content = "".join(f"{start+i+1:4}: {l}" for i, l in enumerate(selected))
            return f"{path} (lines {start+1}-{start+len(selected)} of {total}):\n\n{content}"
        else:
            # Show first 150 lines max to avoid huge messages
            limit = 150
            content = "".join(f"{i+1:4}: {l}" for i, l in enumerate(all_lines[:limit]))
            note = f"\n... ({total - limit} more lines, use 'read {path} 1-{total}' to get all)" if total > limit else ""
            return f"{path} ({total} lines):\n\n{content}{note}"

    except Exception as e:
        return f"Error reading {path}: {e}"


def search_code(pattern: str, path: str = ".", file_glob: str = "*") -> str:
    """Search for a pattern in files (like grep -r)."""
    path = os.path.expanduser(path)

    # Use ripgrep if available (fastest)
    if shutil.which("rg"):
        result = subprocess.run(
            ["rg", "-n", "--max-count", "5", "--glob", file_glob, pattern, path],
            capture_output=True, text=True, timeout=15
        )
        return (result.stdout or result.stderr or "No matches found.")[:3000]

    # Use grep
    if shutil.which("grep"):
        result = subprocess.run(
            ["grep", "-r", "-n", "--include", f"*{file_glob.lstrip('*')}", pattern, path],
            capture_output=True, text=True, timeout=15
        )
        return (result.stdout or "No matches found.")[:3000]

    # Pure Python fallback
    matches = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
        for fname in files:
            if fnmatch.fnmatch(fname, file_glob):
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            if pattern.lower() in line.lower():
                                rel = os.path.relpath(fpath, path)
                                matches.append(f"{rel}:{i}: {line.rstrip()}")
                                if len(matches) >= 50:
                                    break
                except Exception:
                    pass
        if len(matches) >= 50:
            break

    if not matches:
        return f"No matches for '{pattern}' in {path}"
    return f"Found {len(matches)} matches:\n" + "\n".join(matches[:50])


def find_files(pattern: str, path: str = ".") -> str:
    """Find files matching a glob pattern."""
    path = os.path.expanduser(path)
    matches = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git")]
        for fname in files:
            if fnmatch.fnmatch(fname, pattern):
                matches.append(os.path.relpath(os.path.join(root, fname), path))

    if not matches:
        return f"No files matching '{pattern}' in {path}"
    matches.sort()
    return f"Found {len(matches)} files:\n" + "\n".join(matches[:100])


def open_file(path: str) -> str:
    """Open a file in VS Code or default editor."""
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return f"File not found: {path}"
    try:
        if shutil.which("code"):
            subprocess.Popen(["code", path])
            return f"Opened in VS Code: {path}"
        elif OS == "Darwin":
            subprocess.Popen(["open", path])
            return f"Opened: {path}"
        elif OS == "Windows":
            os.startfile(path)
            return f"Opened: {path}"
        else:
            subprocess.Popen(["xdg-open", path])
            return f"Opened: {path}"
    except Exception as e:
        return f"Could not open {path}: {e}"


def tree(path: str = ".", max_depth: int = 3) -> str:
    """Print directory tree."""
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return f"Path not found: {path}"

    IGNORE = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}

    lines = [os.path.abspath(path)]

    def _walk(current_path, prefix, depth):
        if depth > max_depth:
            return
        try:
            entries = sorted(os.scandir(current_path), key=lambda e: (e.is_file(), e.name))
        except PermissionError:
            return
        entries = [e for e in entries if e.name not in IGNORE]
        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{entry.name}{'/' if entry.is_dir() else ''}")
            if entry.is_dir():
                extension = "    " if is_last else "│   "
                _walk(entry.path, prefix + extension, depth + 1)

    _walk(path, "", 1)

    if len(lines) > 200:
        lines = lines[:200]
        lines.append("... (truncated)")

    return "\n".join(lines)


def word_count(path: str) -> str:
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return f"File not found: {path}"
    try:
        with open(path, "r", errors="ignore") as f:
            content = f.read()
        lines = content.count("\n")
        words = len(content.split())
        chars = len(content)
        return f"{path}\n  Lines : {lines}\n  Words : {words}\n  Chars : {chars}"
    except Exception as e:
        return f"Error: {e}"


def handle(cmd: str, args: str) -> str:
    parts = args.strip().split(None, 1)

    if cmd == "read":
        if not parts:
            return "Usage: read <file> [lines]"
        path = parts[0]
        lines_range = parts[1] if len(parts) > 1 else ""
        return read_file(path, lines_range)

    if cmd in ("search", "grep", "find text"):
        if not parts:
            return 'Usage: search "pattern" [path]'
        pattern = parts[0].strip('"\'')
        search_path = parts[1] if len(parts) > 1 else "."
        return search_code(pattern, search_path)

    if cmd in ("find", "locate"):
        if not parts:
            return "Usage: find <pattern>"
        return find_files(parts[0])

    if cmd == "open":
        if not parts:
            return "Usage: open <file>"
        return open_file(parts[0])

    if cmd == "tree":
        path = parts[0] if parts else "."
        depth = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 3
        return tree(path, depth)

    if cmd in ("wc", "wordcount"):
        if not parts:
            return "Usage: wc <file>"
        return word_count(parts[0])

    return f"Unknown file command: {cmd}"
