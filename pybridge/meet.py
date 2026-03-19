"""
meet.py — Start video meetings from your phone command.
Supports Zoom, Google Meet, MS Teams. Works on macOS, Windows, Linux.

Commands:
  meet zoom      → start a new Zoom meeting, return meeting ID/link
  meet google    → open a new Google Meet
  meet teams     → start MS Teams meeting
"""

import os
import re
import shutil
import platform
import subprocess
import threading
import time
import urllib.request
import uuid

OS = platform.system()

# ── Open URL / App ────────────────────────────────────────────────────────────

def open_url(url: str):
    """Open a URL in the default browser, cross-platform."""
    if OS == "Darwin":
        subprocess.Popen(["open", url])
    elif OS == "Windows":
        os.startfile(url)
    elif OS == "Linux":
        subprocess.Popen(["xdg-open", url])

def open_app(path: str, args: list[str] = []):
    """Open a native app."""
    if OS == "Darwin":
        subprocess.Popen(["open", "-a", path] + args)
    elif OS == "Windows":
        subprocess.Popen([path] + args)
    elif OS == "Linux":
        subprocess.Popen([path] + args)

# ── Zoom ──────────────────────────────────────────────────────────────────────

def start_zoom(zoom_path: str = "") -> str:
    """
    Start a Zoom meeting.
    Uses the Zoom URL scheme to open and start a new instant meeting.
    Returns instructions + meeting link concept.
    """
    # Zoom instant meeting via URI scheme
    zoom_uri = "zoommtg://zoom.us/start?confno=&zak="

    try:
        if OS == "Darwin":
            zoom_app = zoom_path or "/Applications/zoom.us.app"
            if os.path.exists(zoom_app):
                # Start Zoom and trigger new meeting via URL scheme
                subprocess.Popen(["open", "-a", zoom_app])
                time.sleep(2)
                # Zoom instant meeting shortcut
                subprocess.Popen(["open", "zoommtg://zoom.us/start?confno=new"])
                return (
                    "Zoom opened — starting new instant meeting.\n"
                    "Meeting ID will appear on screen.\n"
                    "Send 'screenshot' to see it, or 'record 5' to capture it."
                )
            else:
                open_url("https://zoom.us/start/videomeeting")
                return "Zoom desktop not found. Opened Zoom web. Check browser."

        elif OS == "Windows":
            zoom_exe = zoom_path or shutil.which("Zoom") or r"C:\Users\{}\AppData\Roaming\Zoom\bin\Zoom.exe".format(os.environ.get("USERNAME", ""))
            if zoom_exe and os.path.exists(zoom_exe):
                subprocess.Popen([zoom_exe])
                time.sleep(2)
                open_url("zoommtg://zoom.us/start?confno=new")
                return "Zoom opened on Windows. Send 'screenshot' to see meeting ID."
            else:
                open_url("https://zoom.us/start/videomeeting")
                return "Zoom desktop not found. Opened Zoom web."

        elif OS == "Linux":
            if shutil.which("zoom"):
                subprocess.Popen(["zoom"])
                return "Zoom opened on Linux. Send 'screenshot' to see meeting ID."
            else:
                open_url("https://zoom.us/start/videomeeting")
                return "Zoom desktop not found. Opened Zoom web."

    except Exception as e:
        return f"Could not start Zoom: {e}\nTry: https://zoom.us/start/videomeeting"

# ── Google Meet ───────────────────────────────────────────────────────────────

def start_google_meet() -> str:
    """Open a new Google Meet session in the default browser."""
    meet_url = "https://meet.google.com/new"
    try:
        open_url(meet_url)
        return (
            "Google Meet opened in browser.\n"
            "A new meeting link is being generated.\n"
            "Send 'screenshot' to see the meeting link."
        )
    except Exception as e:
        return f"Could not open Google Meet: {e}\nURL: {meet_url}"

# ── Microsoft Teams ───────────────────────────────────────────────────────────

def start_teams(teams_path: str = "") -> str:
    """Start a Microsoft Teams instant meeting."""
    try:
        if OS == "Darwin":
            teams_app = teams_path or "/Applications/Microsoft Teams.app"
            if os.path.exists(teams_app):
                subprocess.Popen(["open", "-a", teams_app])
                return (
                    "MS Teams opened.\n"
                    "Start a new meeting from Teams.\n"
                    "Send 'screenshot' to see the meeting link."
                )
            else:
                open_url("https://teams.microsoft.com/l/meeting/new")
                return "Teams desktop not found. Opened Teams web."

        elif OS == "Windows":
            teams_exe = teams_path or shutil.which("Teams")
            if teams_exe:
                subprocess.Popen([teams_exe])
                return "MS Teams opened. Send 'screenshot' to see meeting."
            else:
                open_url("https://teams.microsoft.com/l/meeting/new")
                return "Teams desktop not found. Opened Teams web."

        elif OS == "Linux":
            if shutil.which("teams") or shutil.which("teams-for-linux"):
                exe = shutil.which("teams") or shutil.which("teams-for-linux")
                subprocess.Popen([exe])
                return "MS Teams opened. Send 'screenshot' to see meeting."
            else:
                open_url("https://teams.microsoft.com/l/meeting/new")
                return "Teams desktop not found. Opened Teams web."

    except Exception as e:
        return f"Could not start Teams: {e}"

# ── Router ────────────────────────────────────────────────────────────────────

def handle_meet(args: str, meeting_cfg: dict) -> str:
    """Handle 'meet <platform>' command."""
    platform_name = args.strip().lower() if args.strip() else "google"

    if platform_name in ("zoom", "z"):
        return start_zoom(meeting_cfg.get("zoom_path", ""))

    elif platform_name in ("google", "meet", "g", "googlemeet"):
        return start_google_meet()

    elif platform_name in ("teams", "t", "msteams"):
        return start_teams(meeting_cfg.get("teams_path", ""))

    else:
        return (
            "Usage: meet <platform>\n"
            "  meet zoom    → Start Zoom meeting\n"
            "  meet google  → Start Google Meet\n"
            "  meet teams   → Start MS Teams meeting\n\n"
            "After starting: send 'screenshot' to see the meeting ID/link."
        )
