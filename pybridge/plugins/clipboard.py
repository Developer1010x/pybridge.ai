"""
plugins/clipboard.py — Read/write clipboard. Cross-platform.

Commands:
  clip            → send clipboard contents to phone
  copy <text>     → set clipboard to <text>
"""

import platform
import subprocess
import shutil
import logging

log = logging.getLogger("pybridge.clipboard")
OS = platform.system()


def get_clipboard() -> str:
    try:
        if OS == "Darwin":
            r = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
            return r.stdout or "(clipboard is empty)"

        elif OS == "Windows":
            r = subprocess.run(
                ["powershell", "-command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=5
            )
            return r.stdout.strip() or "(clipboard is empty)"

        elif OS == "Linux":
            for tool in [("xclip", ["-selection", "clipboard", "-o"]),
                         ("xsel", ["--clipboard", "--output"]),
                         ("wl-paste", [])]:
                if shutil.which(tool[0]):
                    r = subprocess.run([tool[0]] + tool[1], capture_output=True, text=True, timeout=5)
                    return r.stdout or "(clipboard is empty)"
            return "No clipboard tool found. Install xclip or xsel."

    except Exception as e:
        return f"Could not read clipboard: {e}"


def set_clipboard(text: str) -> str:
    try:
        if OS == "Darwin":
            subprocess.run(["pbcopy"], input=text.encode(), timeout=5)
            return f"Clipboard set to: {text[:80]}{'...' if len(text) > 80 else ''}"

        elif OS == "Windows":
            subprocess.run(
                ["powershell", "-command", f"Set-Clipboard '{text}'"],
                timeout=5
            )
            return f"Clipboard set."

        elif OS == "Linux":
            for tool in [("xclip", ["-selection", "clipboard"]),
                         ("xsel", ["--clipboard", "--input"]),
                         ("wl-copy", [])]:
                if shutil.which(tool[0]):
                    subprocess.run([tool[0]] + tool[1], input=text.encode(), timeout=5)
                    return f"Clipboard set."
            return "No clipboard tool found. Install xclip or xsel."

    except Exception as e:
        return f"Could not set clipboard: {e}"


def handle(cmd: str, args: str) -> str:
    if cmd in ("clip", "clipboard", "paste"):
        content = get_clipboard()
        return f"Clipboard:\n{content[:3000]}"

    if cmd in ("copy", "set clipboard"):
        text = args.strip()
        if not text:
            return "Usage: copy <text>"
        return set_clipboard(text)

    return f"Unknown clipboard command: {cmd}"
