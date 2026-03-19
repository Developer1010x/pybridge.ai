from __future__ import annotations
"""
screen.py — Cross-platform screenshot, screen recording, and live stream.
Supports macOS, Windows, Linux.
"""

import os
import sys
import time
import shutil
import socket
import platform
import tempfile
import subprocess
import threading

OS = platform.system()

_stream_process = None
_stream_server = None

# ── Screenshot ────────────────────────────────────────────────────────────────

def take_screenshot() -> str:
    """Take a screenshot and return the temp file path."""
    path = tempfile.mktemp(suffix=".png")

    if OS == "Darwin":
        subprocess.run(["screencapture", "-x", path], check=True)

    elif OS == "Windows":
        try:
            from PIL import ImageGrab
            ImageGrab.grab().save(path)
        except ImportError:
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
                "$s=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
                "$b=New-Object System.Drawing.Bitmap($s.Width,$s.Height);"
                "$g=[System.Drawing.Graphics]::FromImage($b);"
                "$g.CopyFromScreen($s.Location,[System.Drawing.Point]::Empty,$s.Size);"
                f"$b.Save('{path}');"
            )
            subprocess.run(["powershell", "-Command", ps], check=True)

    elif OS == "Linux":
        try:
            from PIL import ImageGrab
            ImageGrab.grab().save(path)
        except Exception:
            if shutil.which("scrot"):
                subprocess.run(["scrot", path], check=True)
            elif shutil.which("gnome-screenshot"):
                subprocess.run(["gnome-screenshot", "-f", path], check=True)
            elif shutil.which("import"):
                subprocess.run(["import", "-window", "root", path], check=True)
            else:
                raise RuntimeError(
                    "No screenshot tool. Install one:\n"
                    "  sudo apt install scrot   (Ubuntu/Debian)\n"
                    "  sudo dnf install scrot   (Fedora)"
                )
    else:
        raise RuntimeError(f"Unsupported OS: {OS}")

    return path

# ── Screen Recording ──────────────────────────────────────────────────────────

def _ffmpeg_input_args() -> list[str]:
    if OS == "Darwin":
        return ["-f", "avfoundation", "-i", "1:none"]
    elif OS == "Windows":
        return ["-f", "gdigrab", "-i", "desktop"]
    elif OS == "Linux":
        display = os.environ.get("DISPLAY", ":0.0")
        return ["-f", "x11grab", "-i", display]
    raise RuntimeError(f"Unsupported OS: {OS}")

def record_screen(seconds: int = 10) -> tuple[str | None, str | None]:
    """Record screen. Returns (file_path, error_or_None)."""
    if not shutil.which("ffmpeg"):
        hints = {
            "Darwin":  "brew install ffmpeg",
            "Windows": "winget install ffmpeg",
            "Linux":   "sudo apt install ffmpeg",
        }
        return None, f"ffmpeg not found. Install: {hints.get(OS, 'ffmpeg')}"

    path = tempfile.mktemp(suffix=".mp4")
    cmd = [
        "ffmpeg", "-y", "-framerate", "15",
        *_ffmpeg_input_args(),
        "-t", str(min(seconds, 60)),
        "-vf", "scale=1280:-2",
        "-c:v", "libx264", "-preset", "fast", "-crf", "28",
        path
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=seconds + 20)
        return path, None
    except subprocess.CalledProcessError as e:
        return None, f"ffmpeg error: {e.stderr.decode()[:300]}"
    except subprocess.TimeoutExpired:
        return None, "Recording timed out"

# ── Live MJPEG Stream ─────────────────────────────────────────────────────────

def start_stream(port: int = 8765) -> str:
    global _stream_process, _stream_server

    if _stream_process and _stream_process.poll() is None:
        return f"Stream already running at port {port}."

    if not shutil.which("ffmpeg"):
        return "ffmpeg not found. Install ffmpeg first."

    jpeg_path = tempfile.mktemp(suffix=".jpg")

    # ffmpeg writes latest frame continuously to same jpeg file
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-framerate", "3",
        *_ffmpeg_input_args(),
        "-vf", "scale=1280:-2",
        "-update", "1",
        "-q:v", "5",
        jpeg_path
    ]
    _stream_process = subprocess.Popen(
        ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    import http.server
    import socketserver

    proc_ref = [_stream_process]

    class MJPEGHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            if self.path != "/":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            while proc_ref[0].poll() is None:
                try:
                    if os.path.exists(jpeg_path):
                        with open(jpeg_path, "rb") as f:
                            data = f.read()
                        self.wfile.write(
                            b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
                        )
                    time.sleep(0.33)
                except Exception:
                    break

    def serve():
        global _stream_server
        with socketserver.TCPServer(("0.0.0.0", port), MJPEGHandler) as httpd:
            _stream_server = httpd
            httpd.serve_forever()

    threading.Thread(target=serve, daemon=True).start()

    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = "YOUR_MAC_IP"

    return (
        f"Live stream started!\n"
        f"Open on your phone (same WiFi):\n"
        f"http://{ip}:{port}/\n"
        f"Send 'stopstream' to stop."
    )

def stop_stream() -> str:
    global _stream_process, _stream_server
    stopped = []
    if _stream_process:
        _stream_process.terminate()
        _stream_process = None
        stopped.append("capture")
    if _stream_server:
        threading.Thread(target=_stream_server.shutdown, daemon=True).start()
        _stream_server = None
        stopped.append("server")
    return f"Stream stopped." if stopped else "No stream was running."
