#!/usr/bin/env python3
"""Linux-only local YTS agent.

Runs on the user's Linux workstation and executes ADB/YTS locally while the
central web application remains hosted in AWS. The agent binds only to
127.0.0.1 and requires a local pairing token for all control endpoints.
"""
import functools
import hmac
import ipaddress
import json
import os
import platform
import secrets
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

from yts_automation import (
    YTS_TEST_COMMANDS,
    YTS_MANUAL_TESTS,
    YTS_TEST_WAIT_SECONDS,
    TEST_INSTRUCTIONS,
    check_adb_devices,
    check_node,
    check_yts_cli,
    discover_yts_devices,
    find_adb,
    get_device_details_cached,
    run_test,
)

if platform.system() != "Linux":
    raise SystemExit("ERROR: YTS Local Agent supports native Linux only.")

HOST = "127.0.0.1"
PORT = int(os.environ.get("YTS_AGENT_PORT", "8765"))
ALLOWED_ORIGIN = os.environ.get("YTS_AGENT_ALLOWED_ORIGIN", "https://yts.webautomation.com").strip()
TOKEN_FILE = Path(os.environ.get("YTS_AGENT_TOKEN_FILE", Path.home() / ".config/yts-automation/agent.token"))
TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)

if TOKEN_FILE.exists():
    TOKEN = TOKEN_FILE.read_text(encoding="utf-8").strip()
else:
    TOKEN = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(TOKEN + "\n", encoding="utf-8")
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": [ALLOWED_ORIGIN]}},
     allow_headers=["Content-Type", "X-YTS-Agent-Token"], methods=["GET", "POST", "OPTIONS"])

sessions = {}
sessions_lock = threading.RLock()
device_locks = {}
device_locks_lock = threading.Lock()


def auth_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        supplied = request.headers.get("X-YTS-Agent-Token", "")
        if not supplied or not hmac.compare_digest(supplied, TOKEN):
            return jsonify({"success": False, "error": "Invalid or missing agent token"}), 401
        return fn(*args, **kwargs)
    return wrapper


def add_cors_private_network(response):
    if request.headers.get("Access-Control-Request-Private-Network") == "true":
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    response.headers["Cache-Control"] = "no-store"
    return response

app.after_request(add_cors_private_network)


def local_networks():
    """Return IPv4 networks assigned to active Linux interfaces."""
    networks = []
    try:
        result = subprocess.run(
            ["ip", "-o", "-4", "addr", "show", "up", "scope", "global"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", timeout=5, check=False,
        )
        for line in result.stdout.splitlines():
            fields = line.split()
            if "inet" not in fields:
                continue
            value = fields[fields.index("inet") + 1]
            try:
                networks.append(ipaddress.ip_interface(value).network)
            except (ValueError, IndexError):
                continue
    except (OSError, subprocess.SubprocessError):
        pass
    return networks


def device_network_status(device_id):
    """Verify an IP-based ADB DUT belongs to one of the user's local subnets."""
    host = str(device_id).rsplit(":", 1)[0]
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # USB/serial ADB does not have an IP address. Keep it visible as local ADB.
        return {"allowed": True, "type": "local", "network": None,
                "reason": "Local/USB ADB device"}
    for network in local_networks():
        if address in network:
            return {"allowed": True, "type": "network", "network": str(network),
                    "reason": "DUT is on the same local subnet as this Linux host"}
    return {"allowed": False, "type": "network", "network": None,
            "reason": "DUT is not on any local subnet of this Linux host"}


def filtered_devices():
    devices = []
    for device_id in check_adb_devices():
        status = device_network_status(device_id)
        if status["allowed"]:
            devices.append((device_id, status))
    return devices


def lock_for(device_id):
    with device_locks_lock:
        return device_locks.setdefault(device_id, threading.Lock())


def validate_device(device_id, short_id):
    if not isinstance(device_id, str) or not device_id.strip():
        return "Missing device_id"
    if not isinstance(short_id, str) or not short_id.strip():
        return "Missing short_id"
    allowed_ids = {device for device, _ in filtered_devices()}
    if device_id not in allowed_ids:
        return "DUT is not connected or is not on the same local network as this Linux host"
    mapping = discover_yts_devices()
    if mapping.get(device_id) != short_id:
        return "YTS short ID does not match the selected DUT"
    return None


@app.get("/health")
def health():
    devices = filtered_devices()
    return jsonify({
        "success": True,
        "agent": "connected",
        "platform": platform.system(),
        "hostname": socket.gethostname(),
        "adb_installed": bool(find_adb()),
        "node_installed": check_node(),
        "yts_installed": check_yts_cli(),
        "device_count": len(devices),
        "devices": [d for d, _ in devices],
        "networks": [str(n) for n in local_networks()],
    })


@app.get("/devices")
@auth_required
def devices():
    mapping = discover_yts_devices()
    result = []
    for device_id, network in filtered_devices():
        short_id = mapping.get(device_id)
        result.append({
            "id": device_id,
            "short_id": short_id or "Not found",
            "has_short_id": bool(short_id),
            "network": network,
        })
    return jsonify({"success": True, "devices": result,
                    "networks": [str(n) for n in local_networks()]})


@app.get("/device-details/<path:device_id>")
@auth_required
def device_details(device_id):
    status = device_network_status(device_id)
    if not status["allowed"]:
        return jsonify({"success": False, "error": status["reason"]}), 403
    return jsonify({"success": True, "device_id": device_id,
                    "details": get_device_details_cached(device_id),
                    "network": status})


@app.get("/test-instruction/<path:test_name>")
@auth_required
def test_instruction(test_name):
    if test_name not in YTS_TEST_COMMANDS:
        return jsonify({"success": False, "error": "Unknown test"}), 404
    return jsonify({"success": True, "test_name": test_name,
                    "instruction": TEST_INSTRUCTIONS.get(test_name, "No instructions available"),
                    "is_manual": test_name in YTS_MANUAL_TESTS,
                    "wait_time": YTS_TEST_WAIT_SECONDS.get(test_name, 0)})


@app.post("/run-test")
@auth_required
def start_test():
    data = request.get_json(silent=True) or {}
    test_name = data.get("test_name")
    device_id = data.get("device_id")
    short_id = data.get("short_id")
    if test_name not in YTS_TEST_COMMANDS:
        return jsonify({"success": False, "error": "Unknown test name"}), 400
    error = validate_device(device_id, short_id)
    if error:
        return jsonify({"success": False, "error": error}), 400
    lock = lock_for(device_id)
    if not lock.acquire(blocking=False):
        return jsonify({"success": False, "error": "This DUT already has a running test"}), 409
    session_id = uuid.uuid4().hex
    with sessions_lock:
        sessions[session_id] = {"test_name": test_name, "device_id": device_id,
                                "short_id": short_id, "status": "running",
                                "result": None, "start_time": time.time(), "logs": []}

    def callback(message):
        with sessions_lock:
            info = sessions.get(session_id)
            if not info:
                return
            seq = info["logs"][-1]["seq"] + 1 if info["logs"] else 1
            info["logs"].append({"seq": seq, "time": time.strftime("%H:%M:%S"),
                                 "message": str(message)})
            if len(info["logs"]) > 500:
                del info["logs"][:-500]

    def worker():
        try:
            result = run_test(short_id, test_name, device_id, callback)
            with sessions_lock:
                sessions[session_id]["status"] = "completed"
                sessions[session_id]["result"] = result
        except Exception as exc:
            with sessions_lock:
                sessions[session_id]["status"] = "failed"
                sessions[session_id]["result"] = "FAILED"
                callback(f"ERROR: {exc}")
        finally:
            lock.release()

    threading.Thread(target=worker, name=f"yts-agent-{session_id[:8]}", daemon=True).start()
    return jsonify({"success": True, "session_id": session_id,
                    "message": f'Test "{test_name}" started'})


@app.get("/test-status/<session_id>")
@auth_required
def test_status(session_id):
    with sessions_lock:
        info = sessions.get(session_id)
        if info is None:
            return jsonify({"success": False, "error": "Session not found"}), 404
        return jsonify({"success": True, **info,
                        "elapsed_time": time.time() - info["start_time"]})


if __name__ == "__main__":
    print("=" * 60)
    print("YTS Linux Local Agent")
    print(f"Listening: http://{HOST}:{PORT}")
    print(f"Allowed web origin: {ALLOWED_ORIGIN}")
    print(f"Pairing token: {TOKEN}")
    print(f"Token file: {TOKEN_FILE}")
    print("Keep this terminal running while using the web application.")
    print("=" * 60)
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
