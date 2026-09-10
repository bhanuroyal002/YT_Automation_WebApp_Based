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

for cmd in python3 node npm; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERROR: '$cmd' is not installed or not in PATH."
        echo "Install the required packages and run this script again."
        exit 1
    fi
done

# Validate native Linux ADB explicitly. A broken adb wrapper may exist earlier
# in PATH, so test the known Linux package path first.
ADB_BIN=""
for candidate in "${ADB_PATH:-}" /usr/bin/adb /usr/local/bin/adb; do
    if [[ -n "$candidate" && -f "$candidate" ]] && "$candidate" version >/dev/null 2>&1; then
        ADB_BIN="$candidate"
        break
    fi
done
if [[ -z "$ADB_BIN" ]]; then
    ADB_BIN="$(command -v adb || true)"
fi
if [[ -z "$ADB_BIN" ]] || ! "$ADB_BIN" version >/dev/null 2>&1; then
    echo "ERROR: No working native Linux ADB client found."
    echo "Install it with: sudo apt update && sudo apt install -y adb"
    exit 1
fi
export ADB_PATH="$ADB_BIN"

printf 'Python : '; python3 --version
printf 'Node   : '; node --version
printf 'npm    : '; npm --version
printf 'ADB    : '; "$ADB_BIN" version | head -n 1

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
    "$ADB_BIN" connect "${ADB_DEVICE}" || true
fi

echo
echo "Starting YTS Automation Web Interface..."
echo "Open: http://${HOST}:${PORT}"
echo "Press Ctrl+C to stop."
echo

exec python app.py
