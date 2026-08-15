"""
channels/repl.py — Local REPL channel.

Feeds stdin through the *same* command router the phone channels use, so the
whole daemon can be exercised with no WhatsApp QR scan, no Telegram bot, no
Gmail app password and no funded API key.

    python main.py --repl                 interactive session
    python main.py --exec "git status"    one command, then exit
    echo "help" | python main.py --repl    piped / non-interactive

Every message is routed through handle_command(), which means the security
gate, the rate limiter, all 12 plugins and the LLM fallback chain behave
exactly as they do for a message arriving from a phone.
"""

import os
import sys
import time
import logging
from pathlib import Path

log = logging.getLogger("pybridge.repl")

IDENTITY = "repl:local"
HISTORY_FILE = Path(os.path.expanduser("~/.pybridge/repl_history"))

# ANSI colours, but only when stdout is a real terminal.
_TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text


DIM = lambda s: _c("2", s)          # noqa: E731
BOLD = lambda s: _c("1", s)         # noqa: E731
BLUE = lambda s: _c("38;5;111", s)  # noqa: E731
GREEN = lambda s: _c("38;5;114", s)  # noqa: E731
RED = lambda s: _c("38;5;203", s)   # noqa: E731

PROMPT = BLUE("pybridge") + BOLD("> ")
EXIT_WORDS = {"exit", "quit", ":q", ":quit", ":exit"}


def _setup_readline():
    """Line editing + persistent history, when readline is available."""
    try:
        import readline
    except ImportError:      # Windows without pyreadline, or a stripped build
        return None
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        if HISTORY_FILE.exists():
            readline.read_history_file(str(HISTORY_FILE))
        readline.set_history_length(1000)
    except OSError as e:
        log.debug(f"readline history unavailable: {e}")
    return readline


def _save_history(readline_mod):
    if readline_mod is None:
        return
    try:
        readline_mod.write_history_file(str(HISTORY_FILE))
    except OSError:
        pass


def _describe_file(path: str) -> str:
    try:
        size = os.path.getsize(path)
    except OSError:
        return f"attachment: {path} (missing)"
    return f"attachment: {path} ({size / 1024:.1f} KB)"


def run_once(handle_command_fn, text: str, identity: str = IDENTITY) -> str:
    """Route one message and print the reply. Returns the reply text."""
    started = time.time()
    try:
        reply, file_path = handle_command_fn(text, identity)
    except Exception as e:                      # a plugin blew up
        log.exception("router error")
        print(RED(f"error: {e}"))
        return f"error: {e}"

    elapsed_ms = int((time.time() - started) * 1000)
    print(reply)
    if file_path:
        print(GREEN(_describe_file(file_path)))
    print(DIM(f"  ({elapsed_ms} ms)"))
    return reply


def _banner(config: dict, current_model: str):
    chain = " → ".join(config.get("fallback_chain", []))
    print()
    print(BOLD("  PyBridge REPL") + DIM("  —  the same router your phone talks to"))
    print(DIM(f"  model: {current_model}   fallback: {chain}"))
    print(DIM("  try:  help  ·  status  ·  git status  ·  ping 1.1.1.1  ·  exit"))
    print()


def repl_loop(config: dict, handle_command_fn, current_model: str = "",
              identity: str = IDENTITY):
    """Read commands from stdin until EOF or an exit word."""
    interactive = sys.stdin.isatty()
    readline_mod = _setup_readline() if interactive else None

    if interactive:
        _banner(config, current_model or config.get("default_model", "?"))
    log.info(f"[repl] channel ready (identity={identity})")

    try:
        while True:
            try:
                if interactive:
                    line = input(PROMPT)
                else:
                    line = sys.stdin.readline()
                    if line == "":
                        break
                    line = line.rstrip("\n")
                    print(f"{PROMPT}{line}")
            except KeyboardInterrupt:
                print("\n" + DIM("(interrupted — type exit to quit)"))
                continue
            except EOFError:
                print()
                break

            text = line.strip()
            if not text:
                continue
            if text.lower() in EXIT_WORDS:
                break

            run_once(handle_command_fn, text, identity)
    finally:
        _save_history(readline_mod)
        print(DIM("repl closed."))
