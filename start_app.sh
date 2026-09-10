#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

# This launcher is intentionally usable from both native Linux/WSL and Windows
# (via WSL). For native Windows, use start_app.bat instead.

echo "=================================================="
echo "  YTS Automation Web Interface"
echo "=================================================="

OS_NAME="$(uname -s 2>/dev/null || true)"
if [[ "$OS_NAME" == MINGW* || "$OS_NAME" == MSYS* || "$OS_NAME" == CYGWIN* ]]; then
    echo "Environment: Windows shell"
else
    if grep -qi microsoft /proc/version 2>/dev/null; then
        echo "Environment: WSL"
    else
        echo "Environment: Linux"
    fi
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

# ADB is selected by adb_platform.py. We deliberately do not execute
# /usr/local/bin/adb here because it may be a broken Windows-interoperability
# wrapper under WSL. If this is WSL and no working Linux ADB is installed,
# install the native ADB client so WSL can talk directly to network-connected
# DUTs without depending on Windows .exe interop.
if grep -qi microsoft /proc/version 2>/dev/null; then
    if ! (command -v adb >/dev/null 2>&1 && adb version >/dev/null 2>&1); then
        if command -v apt-get >/dev/null 2>&1; then
            echo
            echo "[INFO] Native Linux ADB is not working in WSL."
            echo "[INFO] Installing the WSL ADB client (android-tools-adb)..."
            sudo apt-get update
            sudo apt-get install -y adb
        else
            echo "ERROR: WSL ADB is not working and apt-get is unavailable."
            echo "Install the Linux ADB client and run this script again."
            exit 1
        fi
    fi
fi

mkdir -p data

export HOST="${HOST:-127.0.0.1}"
export PORT="${PORT:-5000}"
export FLASK_DEBUG="${FLASK_DEBUG:-0}"

# For a network-connected DUT, set ADB_DEVICE once, for example:
#   export ADB_DEVICE=192.168.1.7:5555
# The application will run 'adb connect' in the current OS environment.
if [[ -n "${ADB_DEVICE:-}" ]]; then
    echo "ADB device target: ${ADB_DEVICE}"
fi

echo
echo "Starting YTS Automation Web Interface..."
echo "Open: http://${HOST}:${PORT}"
echo "Press Ctrl+C to stop."
echo

exec python app.py
