#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "ERROR: The YTS Local Agent supports native Linux only."
    exit 1
fi

for cmd in python3 adb node npm; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERROR: Required command not found: $cmd"
        exit 1
    fi
done

PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ ! -d .agent-venv ]]; then
    "$PYTHON_BIN" -m venv .agent-venv
fi

source .agent-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

export YTS_AGENT_ALLOWED_ORIGIN="${YTS_AGENT_ALLOWED_ORIGIN:-https://yts.webautomation.com}"
export YTS_AGENT_PORT="${YTS_AGENT_PORT:-8765}"

echo
echo "Starting YTS Linux Local Agent"
echo "Web origin: $YTS_AGENT_ALLOWED_ORIGIN"
echo "Agent: http://127.0.0.1:$YTS_AGENT_PORT"
echo
exec python agent.py
