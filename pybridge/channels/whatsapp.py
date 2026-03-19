"""
channels/whatsapp.py — WhatsApp channel for PyBridge.

Talks to the local Node.js whatsapp_bridge/server.js over HTTP (localhost only).
The bridge uses whatsapp-web.js to connect your WhatsApp account.
"""

import os
import time
import logging
import subprocess
import shutil
import threading
import requests

log = logging.getLogger("pybridge.whatsapp")

_bridge_process = None


# ── Bridge management ─────────────────────────────────────────────────────────

def _bridge_url(path: str, port: int) -> str:
    return f"http://127.0.0.1:{port}{path}"


def start_bridge(bridge_dir: str, port: int):
    """Start the Node.js WhatsApp bridge server."""
    global _bridge_process

    node = shutil.which("node") or shutil.which("nodejs")
    if not node:
        log.error("Node.js not found. Install Node.js 18+.")
        return False

    server_js = os.path.join(bridge_dir, "server.js")
    nm = os.path.join(bridge_dir, "node_modules")

    # Install deps if needed
    if not os.path.exists(nm):
        log.info("[whatsapp] Installing bridge dependencies (first time)...")
        npm = shutil.which("npm")
        if not npm:
            log.error("npm not found.")
            return False
        subprocess.run([npm, "install"], cwd=bridge_dir, check=True)

    log.info("[whatsapp] Starting bridge server...")
    _bridge_process = subprocess.Popen(
        [node, server_js],
        cwd=bridge_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # Stream bridge logs in background
    def _stream_logs():
        for line in _bridge_process.stdout:
            line = line.rstrip()
            if line:
                log.info(f"[wa-bridge] {line}")

    threading.Thread(target=_stream_logs, daemon=True).start()

    # Wait for bridge HTTP server to come up
    for _ in range(30):
        time.sleep(1)
        try:
            resp = requests.get(_bridge_url("/status", port), timeout=2)
            if resp.status_code == 200:
                log.info("[whatsapp] Bridge is up.")
                # Open QR popup window in its own thread (Tkinter must run on main-ish thread)
                _open_qr_popup(port)
                return True
        except Exception:
            pass

    log.warning("[whatsapp] Bridge did not respond in 30s.")
    return False


def _open_qr_popup(port: int):
    """Launch the QR popup as a separate process (tkinter needs the main thread)."""
    try:
        import sys, os
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        popup_script = os.path.join(base, "qr_popup.py")
        subprocess.Popen(
            [sys.executable, popup_script, str(port)],
            start_new_session=True,
        )
        log.info("[whatsapp] QR popup launched — check your screen.")
    except Exception as e:
        log.warning(f"[whatsapp] QR popup failed: {e}")


def stop_bridge():
    global _bridge_process
    if _bridge_process:
        _bridge_process.terminate()
        _bridge_process = None


def is_bridge_ready(port: int) -> bool:
    try:
        resp = requests.get(_bridge_url("/status", port), timeout=2)
        return resp.json().get("ready", False)
    except Exception:
        return False


# ── Send ──────────────────────────────────────────────────────────────────────

def send_message(to: str, message: str, port: int):
    try:
        requests.post(
            _bridge_url("/send", port),
            json={"to": to, "message": message},
            timeout=15,
        ).raise_for_status()
    except Exception as e:
        log.error(f"[whatsapp] Send failed: {e}")


def send_image(to: str, image_path: str, caption: str, port: int):
    try:
        requests.post(
            _bridge_url("/send-image", port),
            json={"to": to, "image_path": image_path, "caption": caption},
            timeout=30,
        ).raise_for_status()
        if os.path.exists(image_path):
            os.remove(image_path)
    except Exception as e:
        log.error(f"[whatsapp] Send image failed: {e}")


def send_video(to: str, video_path: str, caption: str, port: int):
    try:
        requests.post(
            _bridge_url("/send-video", port),
            json={"to": to, "video_path": video_path, "caption": caption},
            timeout=60,
        ).raise_for_status()
        if os.path.exists(video_path):
            os.remove(video_path)
    except Exception as e:
        log.error(f"[whatsapp] Send video failed: {e}")


# ── Poll loop ─────────────────────────────────────────────────────────────────

def whatsapp_loop(config: dict, handle_command_fn, bridge_dir: str):
    """
    Main WhatsApp loop.
    Polls bridge for incoming messages, routes through handle_command_fn,
    sends reply back.
    """
    wa_cfg = config.get("whatsapp", {})
    port = wa_cfg.get("bridge_port", 8766)
    interval = wa_cfg.get("check_interval_seconds", 3)

    # Start bridge
    started = start_bridge(bridge_dir, port)
    if not started:
        log.warning("[whatsapp] Bridge may not be ready yet — will keep retrying.")

    log.info(f"[whatsapp] Polling every {interval}s")

    while True:
        try:
            if not is_bridge_ready(port):
                time.sleep(5)
                continue

            resp = requests.get(_bridge_url("/messages", port), timeout=5)
            messages = resp.json()

            for msg in messages:
                sender = msg["from"]          # e.g. "919876543210@c.us"
                number = msg["from_number"]   # e.g. "919876543210"
                text = msg.get("body", "").strip()

                if not text:
                    continue

                identity = f"whatsapp:{number}"
                log.info(f"[whatsapp] {number}: {text[:60]}")

                reply, file_path = handle_command_fn(text, identity)

                if file_path and os.path.exists(file_path):
                    if file_path.endswith(".png"):
                        send_image(sender, file_path, reply[:200], port)
                    elif file_path.endswith(".mp4"):
                        send_video(sender, file_path, reply[:200], port)
                else:
                    # WhatsApp has no hard message limit but keep it sane
                    for chunk in [reply[i:i+3000] for i in range(0, len(reply), 3000)]:
                        send_message(sender, chunk, port)

        except Exception as e:
            log.error(f"[whatsapp] Loop error: {e}")

        time.sleep(interval)
