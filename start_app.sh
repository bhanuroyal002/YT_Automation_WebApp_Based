#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

echo "=================================================="
echo "  YTS Automation Tool - Linux"
echo "=================================================="

echo

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "ERROR: This project supports Linux only."
    exit 1
fi

# Install required Ubuntu/Debian system packages automatically when possible.
# This keeps the user setup to one command after cloning the repository.
install_system_dependencies() {
    local missing=()
    command -v python3 >/dev/null 2>&1 || missing+=(python3)
    command -v node >/dev/null 2>&1 || missing+=(nodejs)
    command -v npm >/dev/null 2>&1 || missing+=(npm)
    command -v adb >/dev/null 2>&1 || missing+=(adb)

    if [[ ${#missing[@]} -eq 0 ]]; then
        return 0
    fi

    if ! command -v apt-get >/dev/null 2>&1; then
        echo "ERROR: Missing system dependencies: ${missing[*]}"
        echo "This automatic installer supports Ubuntu/Debian (apt)."
        exit 1
    fi

    if [[ $EUID -eq 0 ]]; then
        SUDO=""
    elif command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        echo "ERROR: Missing system dependencies: ${missing[*]}"
        echo "Please install them with root privileges and run this script again."
        exit 1
    fi

    echo "Installing missing Linux dependencies: ${missing[*]}"
    $SUDO apt-get update
    $SUDO apt-get install -y python3 python3-venv python3-pip nodejs npm adb
}

install_system_dependencies

# python3-venv is required for the isolated project environment.
if ! python3 -m venv --help >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
        if [[ $EUID -eq 0 ]]; then SUDO=""; elif command -v sudo >/dev/null 2>&1; then SUDO="sudo"; else SUDO=""; fi
        $SUDO apt-get update
        $SUDO apt-get install -y python3-venv python3-pip
    fi
fi

# Verify the required tools after installation.
for cmd in python3 node npm adb; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERROR: '$cmd' is not installed or not in PATH."
        exit 1
    fi
done

# Validate that ADB is a native Linux executable and not a Windows/WSL wrapper.
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

# Create and maintain an isolated Python environment for the application.
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
echo "Starting YTS Automation Tool..."
echo "Open: http://${HOST}:${PORT}"
echo "Press Ctrl+C to stop."
echo

exec python app.py
