#!/bin/bash
# Start PyBridge on macOS / Linux

cd "$(dirname "$0")"

# Use Python 3.11 if available, else fallback to python3
PYTHON=$(which python3.11 2>/dev/null || which python3)
echo "Using Python: $PYTHON ($($PYTHON --version))"

echo "Starting PyBridge..."
$PYTHON main.py
