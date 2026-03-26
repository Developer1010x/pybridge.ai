#!/usr/bin/env python3
"""
PyBridge Tray App - System tray application for PyBridge
Runs in background, shows status, allows quick actions.

Install: pip install pystray pillow pywin32
Build:   pyinstaller --onefile --noconsole --icon=icon.ico pybridge_tray.py
"""

import os
import sys
import json
import threading
import time
import socket
import platform
import subprocess
from pathlib import Path

try:
    from pystray import MenuItem as Item
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    print("Missing dependencies. Install: pip install pystray pillow")
    sys.exit(1)

OS = platform.system()
BASE_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = BASE_DIR / "pybridge" / "config.json"

_running = True
_pybridge_process = None

# ── Config ───────────────────────────────────────────────────────────────────

def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}

def get_status():
    status = {"pybridge": "stopped", "opencode": "stopped", "whatsapp": "stopped"}
    
    try:
        if OS == "Windows":
            out = subprocess.check_output(["tasklist"], stderr=subprocess.DEVNULL, text=True)
            if "python" in out.lower():
                status["pybridge"] = "running"
        else:
            out = subprocess.check_output(["pgrep", "-f", "main.py"], stderr=subprocess.DEVNULL, text=True)
            if out.strip():
                status["pybridge"] = "running"
    except:
        pass
    
    try:
        req = urllib.request.Request("http://localhost:54321/health")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                status["opencode"] = "running"
    except:
        pass
    
    return status

def check_port(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(("localhost", port))
    sock.close()
    return result == 0

# ── Tray Icon ───────────────────────────────────────────────────────────────

def create_icon():
    size = 64
    img = Image.new("RGB", (size, size), color=(30, 30, 40))
    draw = ImageDraw.Draw(img)
    
    draw.ellipse([8, 8, 56, 56], fill=(108, 140, 255))
    draw.rectangle([20, 24, 44, 40], fill=(255, 255, 255))
    draw.polygon([(32, 16), (24, 28), (40, 28)], fill=(255, 255, 255))
    
    return img

# ── Actions ───────────────────────────────────────────────────────────────

def start_pybridge():
    global _pybridge_process
    if _pybridge_process and _pybridge_process.poll() is None:
        return
    
    pybridge_path = BASE_DIR / "pybridge" / "main.py"
    if pybridge_path.exists():
        if OS == "Windows":
            _pybridge_process = subprocess.Popen(
                [sys.executable, str(pybridge_path)],
                creationflags=subprocess.CREATE_NO_WINDOW,
                cwd=str(BASE_DIR / "pybridge"),
            )
        else:
            _pybridge_process = subprocess.Popen(
                [sys.executable, str(pybridge_path)],
                cwd=str(BASE_DIR / "pybridge"),
            )

def stop_pybridge():
    global _pybridge_process
    if _pybridge_process and _pybridge_process.poll() is None:
        _pybridge_process.terminate()
        _pybridge_process = None

def open_control_panel():
    import webbrowser
    webbrowser.open("http://localhost:9090")

def open_config_folder():
    if OS == "Windows":
        os.startfile(BASE_DIR / "pybridge")
    else:
        subprocess.run(["open", str(BASE_DIR / "pybridge")])

def stop_app(icon):
    global _running
    _running = False
    stop_pybridge()
    icon.stop()

# ── Menu ───────────────────────────────────────────────────────────────────

def get_menu(icon):
    status = get_status()
    
    def status_text(service):
        s = status.get(service, "stopped")
        return f"{service.capitalize()}: {s.capitalize()}"
    
    menu = [
        Item("PyBridge", lambda: None, enabled=False),
        Item(status_text("pybridge"), lambda: None, enabled=False),
        Item(status_text("opencode"), lambda: None, enabled=False),
        Item("---", lambda: None, enabled=False),
        Item("Open Control Panel", lambda _: open_control_panel()),
        Item("Open Config Folder", lambda _: open_config_folder()),
        Item("---", lambda: None, enabled=False),
        Item("Start PyBridge", lambda _: start_pybridge()),
        Item("Stop PyBridge", lambda _: stop_pybridge()),
        Item("---", lambda: None, enabled=False),
        Item("Exit", lambda _: stop_app(icon)),
    ]
    
    return menu

# ── Main ───────────────────────────────────────────────────────────────────

def main():
    global _running
    
    icon = pystray.Icon(
        "pybridge",
        create_icon(),
        "PyBridge AI Control",
        menu=get_menu(None),
    )
    
    def update_menu(icon):
        icon.menu = get_menu(icon)
    
    def runner():
        while _running:
            try:
                time.sleep(5)
                update_menu(icon)
            except:
                break
    
    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    
    icon.run()

if __name__ == "__main__":
    main()
