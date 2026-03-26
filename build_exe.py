# PyBridge Build Script
# Creates a standalone executable for Windows

# Requirements:
# pip install pyinstaller pillow pystray

# Run this from the pybridge.ai directory:
# python build_exe.py

import os
import sys
import subprocess

def install_deps():
    deps = ["pyinstaller", "pillow", "pystray"]
    for dep in deps:
        subprocess.run([sys.executable, "-m", "pip", "install", dep])

def build():
    # Build main exe
    pyinstaller_cmd = [
        "pyinstaller",
        "--onefile",
        "--noconsole",
        "--name", "PyBridge",
        "--add-data", "pybridge;pybridge",
        "--hidden-import", "pystray",
        "--hidden-import", "PIL",
        "--hidden-import", "email",
        "--hidden-import", "imaplib",
        "--hidden-import", "smtplib",
        "--collect-all", "pystray",
        "pybridge_tray.py"
    ]
    
    print("Building PyBridge.exe...")
    subprocess.run(pyinstaller_cmd)
    print("Done! Check dist/PyBridge.exe")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--install":
        install_deps()
    else:
        build()
