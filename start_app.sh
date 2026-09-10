#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

echo "=================================================="
echo "  YTS Automation Web Interface"
echo "=================================================="

if grep -qi microsoft /proc/version 2>/dev/null; then
    echo "Environment: WSL"
elif [[ "$(uname -s 2>/dev/null || true)" == Linux* ]]; then
    echo "Environment: Linux"
else
    echo "Environment: Unix-like shell"
fi

for cmd in python3 node npm; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERROR: '$cmd' is not installed or not in PATH."
        exit 1
    fi
done

echo "Python : $(python3 --version)"
echo "Node   : $(node --version)"
echo "npm    : $(npm --version)"

if [[ ! -d ".venv" ]]; then
    echo "Creating Python virtual environment..."
    python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Ensure a native Linux ADB client is available under Linux/WSL.
if grep -qi microsoft /proc/version 2>/dev/null || [[ "$(uname -s 2>/dev/null || true)" == Linux* ]]; then
    if ! /usr/bin/adb version >/dev/null 2>&1 && ! adb version >/dev/null 2>&1; then
        if command -v apt-get >/dev/null 2>&1; then
            echo "[INFO] Native Linux ADB is not available. Installing android-tools-adb..."
            sudo apt-get update
            sudo apt-get install -y adb
        else
            echo "ERROR: Native Linux ADB is unavailable and apt-get is not installed."
            exit 1
        fi
    fi
fi

mkdir -p data
export HOST="${HOST:-127.0.0.1}"
export PORT="${PORT:-5000}"
export FLASK_DEBUG="${FLASK_DEBUG:-0}"

if [[ -n "${ADB_DEVICE:-}" ]]; then
    echo "ADB device target: ${ADB_DEVICE}"
fi

echo
echo "Starting YTS Automation Web Interface..."
echo "Open: http://${HOST}:${PORT}"
echo "Press Ctrl+C to stop."
echo

exec python app.py
