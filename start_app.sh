#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

echo "=================================================="
echo "  YTS Automation Web Interface - Linux"

echo "=================================================="

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "ERROR: This project supports Linux only."
    exit 1
fi

for cmd in python3 node npm adb; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERROR: '$cmd' is not installed or not in PATH."
        echo "Install the required packages and run this script again."
        exit 1
    fi
done

echo "Python : $(python3 --version)"
echo "Node   : $(node --version)"
echo "npm    : $(npm --version)"
echo "ADB    : $(adb version | head -n 1)"

if [[ ! -d ".venv" ]]; then
    echo "Creating Python virtual environment..."
    python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

mkdir -p data

export HOST="${HOST:-127.0.0.1}"
export PORT="${PORT:-5000}"
export FLASK_DEBUG="${FLASK_DEBUG:-0}"

if [[ -n "${ADB_DEVICE:-}" ]]; then
    echo "ADB device target: ${ADB_DEVICE}"
    adb connect "${ADB_DEVICE}" || true
fi

echo
echo "Starting YTS Automation Web Interface..."
echo "Open: http://${HOST}:${PORT}"
echo "Press Ctrl+C to stop."
echo

exec python app.py
