"""
qr_popup.py
Polls the WhatsApp bridge for a QR code and shows it in a Tkinter window.
Closes automatically when WhatsApp is authenticated.
"""
from __future__ import annotations

import io
import time
import threading
import tkinter as tk
from tkinter import ttk
from urllib import request as urllib_request
import json

try:
    import qrcode
    from PIL import Image, ImageTk
    _DEPS = True
except ImportError:
    _DEPS = False


def _fetch(url: str, timeout: int = 3):
    try:
        with urllib_request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def show_qr_window(port: int = 8766):
    """
    Open a window that shows the WhatsApp QR code.
    Polls the bridge every 2 s; closes when ready=True or window is dismissed.
    """
    if not _DEPS:
        print("[qr_popup] Missing deps: pip install qrcode[pil] Pillow")
        return

    root = tk.Tk()
    root.title("PyBridge — Scan with WhatsApp")
    root.resizable(False, False)

    # Keep window on top
    root.attributes("-topmost", True)

    # ── Layout ────────────────────────────────────────────────────────────────
    frame = tk.Frame(root, bg="#ffffff", padx=20, pady=20)
    frame.pack(fill="both", expand=True)

    header = tk.Label(
        frame,
        text="Scan with WhatsApp",
        font=("Helvetica", 16, "bold"),
        bg="#ffffff", fg="#128C7E",
    )
    header.pack(pady=(0, 4))

    sub = tk.Label(
        frame,
        text="WhatsApp → Settings → Linked Devices → Link a Device",
        font=("Helvetica", 10),
        bg="#ffffff", fg="#555555",
    )
    sub.pack(pady=(0, 12))

    qr_label = tk.Label(frame, bg="#ffffff")
    qr_label.pack()

    status_var = tk.StringVar(value="Waiting for QR code…")
    status_lbl = tk.Label(
        frame,
        textvariable=status_var,
        font=("Helvetica", 10),
        bg="#ffffff", fg="#888888",
    )
    status_lbl.pack(pady=(8, 0))

    _current_qr: dict = {"data": None, "photo": None}

    # ── Polling thread ────────────────────────────────────────────────────────

    def _poll():
        base = f"http://127.0.0.1:{port}"
        while True:
            data = _fetch(f"{base}/qr")
            if data is None:
                status_var.set("Bridge not reachable — retrying…")
                time.sleep(2)
                continue

            if data.get("ready"):
                status_var.set("✅  Connected! You can close this window.")
                time.sleep(2)
                root.after(0, root.destroy)
                return

            qr_str = data.get("qr")
            if qr_str and qr_str != _current_qr["data"]:
                _current_qr["data"] = qr_str
                # Generate QR image
                img = qrcode.make(qr_str, box_size=6, border=2)
                img = img.resize((280, 280), Image.NEAREST)
                photo = ImageTk.PhotoImage(img)
                _current_qr["photo"] = photo   # keep reference
                root.after(0, lambda p=photo: _set_image(p))
                root.after(0, lambda: status_var.set("Scan the QR code above ↑"))
            elif not qr_str:
                status_var.set("Waiting for QR code…")

            time.sleep(2)

    def _set_image(photo):
        qr_label.config(image=photo)
        qr_label.image = photo

    t = threading.Thread(target=_poll, daemon=True)
    t.start()

    root.mainloop()


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    show_qr_window(port)
