from __future__ import annotations
"""
plugins/git_github.py — Git & GitHub commands.

Commands:
  git status          → current branch + changes
  git log 5           → last N commits
  git diff            → unstaged changes
  git pull            → pull latest
  git branches        → list branches
  pr list             → open PRs
  pr status           → PR CI status
  pr create <title>   → create PR from current branch
  issue list          → open issues
  issue <number>      → show issue details
  deploy              → trigger latest CI/CD workflow
"""

import subprocess
import shutil
import os
import json
import logging

log = logging.getLogger("pybridge.git")


def _git(args: list[str], cwd: str = None) -> str:
    if not shutil.which("git"):
        return "git not found. Install git."
    cwd = cwd or os.getcwd()
    try:
        r = subprocess.run(
            ["git"] + args, capture_output=True, text=True, timeout=20, cwd=cwd
        )
        out = r.stdout.strip()
        err = r.stderr.strip()
        return out or err or "(no output)"
    except subprocess.TimeoutExpired:
        return "git command timed out"
    except Exception as e:
        return f"git error: {e}"


def _gh(args: list[str], cwd: str = None) -> str:
    if not shutil.which("gh"):
        return "GitHub CLI (gh) not found. Install: https://cli.github.com"
    cwd = cwd or os.getcwd()
    try:
        r = subprocess.run(
            ["gh"] + args, capture_output=True, text=True, timeout=20, cwd=cwd
        )
        out = r.stdout.strip()
        err = r.stderr.strip()
        return out or err or "(no output)"
    except subprocess.TimeoutExpired:
        return "gh command timed out"
    except Exception as e:
        return f"gh error: {e}"


def _find_git_root() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5
        )
        path = result.stdout.strip()
        return path if path else None
    except Exception:
        return None


def handle(cmd: str, args: str) -> str:
    cwd = _find_git_root() or os.getcwd()

    # git status
    if cmd in ("git status", "gst", "status"):
        branch = _git(["branch", "--show-current"], cwd)
        status = _git(["status", "--short"], cwd)
        staged = _git(["diff", "--cached", "--stat"], cwd)
        result = f"Branch: {branch}\n"
        result += f"Changes:\n{status}" if status else "Changes: clean"
        if staged:
            result += f"\nStaged:\n{staged}"
        return result

    # git log
    if cmd in ("git log", "glog", "log"):
        n = args.strip() or "5"
        try:
            n = int(n)
        except ValueError:
            n = 5
        return _git(["log", f"-{n}", "--oneline", "--decorate"], cwd)

    # git diff
    if cmd in ("git diff", "diff"):
        target = args.strip() or ""
        if target:
            return _git(["diff", target], cwd)[:3000]
        return _git(["diff", "--stat"], cwd)

    # git pull
    if cmd in ("git pull", "pull"):
        return _git(["pull"], cwd)

    # git push
    if cmd in ("git push", "push"):
        return _git(["push"], cwd)

    # git branches
    if cmd in ("git branches", "branches"):
        return _git(["branch", "-a", "--sort=-committerdate"], cwd)

    # git stash
    if cmd in ("git stash", "stash"):
        if "pop" in args:
            return _git(["stash", "pop"], cwd)
        return _git(["stash"], cwd)

    # PRs
    if cmd in ("pr list", "prs"):
        return _gh(["pr", "list", "--limit", "10"], cwd)

    if cmd in ("pr status",):
        return _gh(["pr", "status"], cwd)

    if cmd.startswith("pr create"):
        title = args.strip() or "Update from PyBridge"
        return _gh(["pr", "create", "--title", title, "--body", "Created via PyBridge", "--fill"], cwd)

    if cmd.startswith("pr view"):
        num = args.strip()
        if num:
            return _gh(["pr", "view", num], cwd)
        return _gh(["pr", "view"], cwd)

    if cmd.startswith("pr merge"):
        num = args.strip()
        if num:
            return _gh(["pr", "merge", num, "--squash", "--auto"], cwd)
        return _gh(["pr", "merge", "--squash", "--auto"], cwd)

    # Issues
    if cmd in ("issue list", "issues"):
        return _gh(["issue", "list", "--limit", "10"], cwd)

    if cmd.startswith("issue "):
        num = args.strip()
        if num.isdigit():
            return _gh(["issue", "view", num], cwd)
        return _gh(["issue", "list", "--search", num, "--limit", "5"], cwd)

    # Deploy / CI
    if cmd in ("deploy", "ci", "workflow"):
        runs = _gh(["run", "list", "--limit", "5"], cwd)
        return f"Recent CI runs:\n{runs}"

    if cmd.startswith("deploy "):
        workflow = args.strip()
        return _gh(["workflow", "run", workflow], cwd)

    return f"Unknown git command: {cmd}"
