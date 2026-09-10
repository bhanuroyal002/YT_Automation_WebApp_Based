#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_DIR="$APP_DIR/agent"
cd "$APP_DIR"

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "ERROR: YTS Linux Agent supports native Linux only."
    exit 1
fi

for cmd in python3 adb node; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERROR: Required command not found: $cmd"
        exit 1
    fi
done

if [[ ! -d "$APP_DIR/.agent-venv" ]]; then
    python3 -m venv "$APP_DIR/.agent-venv"
fi

source "$APP_DIR/.agent-venv/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r "$AGENT_DIR/requirements.txt"

export YTS_AGENT_PORT="${YTS_AGENT_PORT:-8765}"
export YTS_SERVER_URL="${YTS_SERVER_URL:-https://yts.webautomation.com}"
export YTS_AGENT_ALLOWED_ORIGINS="${YTS_AGENT_ALLOWED_ORIGINS:-https://yts.webautomation.com}"
export ADB_PATH="${ADB_PATH:-$(command -v adb)}"

exec python "$AGENT_DIR/agent.py"
