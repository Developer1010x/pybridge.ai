@echo off
REM Start PyBridge on Windows

cd /d "%~dp0"

echo Starting PyBridge...
REM Pass through any flags, e.g. start.bat --repl
python main.py %*
pause
