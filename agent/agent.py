#!/usr/bin/env python3
"""Linux-only local YTS agent.

The agent runs on the user's Linux workstation, not on the EC2 server.
It owns native ADB/YTS access and only binds to loopback so DUTs are never
exposed through the agent service.
"""
import ipaddress
import json
import logging
import os
import re
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib import request as urlrequest

from flask import Flask, jsonify, request
from flask_cors import CORS

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yts_automation import (  # noqa: E402
    TEST_INSTRUCTIONS,
    TEST_CATEGORIES,
    YTS_MANUAL_TESTS,
    YTS_TEST_COMMANDS,
    YTS_TEST_WAIT_SECONDS,
    check_adb_devices,
    check_node,
    check_yts_cli,
    discover_yts_devices,
    find_adb,
    get_device_details_cached,
    run_test,
)

HOST = "127.0.0.1"
PORT = int(os.environ.get("YTS_AGENT_PORT", "8765"))
SERVER_URL = os.environ.get("YTS_SERVER_URL", "").rstrip("/")
ALLOWED_ORIGINS = [
    item.strip() for item in os.environ.get(
        "YTS_AGENT_ALLOWED_ORIGINS",
        "https://yts.webautomation.com,http://localhost:5000,http://127.0.0.1:5000",
    ).split(",") if item.strip()
]

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}})
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("yts-agent")

sessions = {}
sessions_lock = threading.RLock()
device_locks = {}
device_locks_lock = threading.Lock()


def json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def get_device_lock(device_id):
    with device_locks_lock:
        return device_locks.setdefault(device_id, threading.Lock())


def local_ipv4_networks():
    """Return non-loopback IPv4 networks configured on this Linux host."""
    networks = []
    try:
        result = subprocess.run(
            ["ip", "-j", "-4", "addr", "show"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        data = json.loads(result.stdout or "[]")
        for interface in data:
            name = interface.get("ifname", "")
            if name == "lo" or name.startswith(("docker", "br-", "veth", "virbr")):
                continue
            for address in interface.get("addr_info", []):
                if address.get("family") != "inet":
                    continue
                local = address.get("local")
                prefix = address.get("prefixlen")
                if not local or prefix is None:
                    continue
                try:
                    networks.append({
                        "interface": name,
                        "address": local,
                        "network": str(ipaddress.ip_network(f"{local}/{prefix}", strict=False)),
                    })
                except ValueError:
                    continue
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        logger.warning("Unable to inspect Linux interfaces: %s", exc)
    return networks


def extract_host(device_id):
    if not isinstance(device_id, str):
        return None
    value = device_id.strip()
    if not value:
        return None
    if value.startswith("[") and "]" in value:
        return value[1:value.index("]")]
    if value.count(":") == 1:
        return value.rsplit(":", 1)[0]
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        return None


def resolve_ipv4(host):
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
            return infos[0][4][0] if infos else None
        except socket.gaierror:
            return None


def validate_dut_network(device_id):
    """Require network ADB DUTs to be on a subnet local to this Linux host."""
    host = extract_host(device_id)
    if not host:
        return False, "DUT must be a network ADB device such as <ip>:5555"
    dut_ip = resolve_ipv4(host)
    if not dut_ip:
        return False, f"Could not resolve DUT address: {host}"
    try:
        dut = ipaddress.ip_address(dut_ip)
    except ValueError:
        return False, f"Invalid DUT IPv4 address: {dut_ip}"
    networks = local_ipv4_networks()
    for item in networks:
        if dut in ipaddress.ip_network(item["network"]):
            return True, f"DUT {dut_ip} is on local network {item['network']} via {item['interface']}"
    local = ", ".join(item["network"] for item in networks) or "none detected"
    return False, f"DUT {dut_ip} is not on the Linux host's local network. Local networks: {local}"


def network_devices():
    devices = check_adb_devices()
    accepted = []
    rejected = {}
    for device in devices:
        ok, reason = validate_dut_network(device)
        if ok:
            accepted.append(device)
        else:
            rejected[device] = reason
    return accepted, rejected


def discover_devices():
    devices, rejected = network_devices()
    mappings = discover_yts_devices() if devices else {}
    result = []
    for device in devices:
        result.append({
            "id": device,
            "short_id": mappings.get(device, "Not found"),
            "has_short_id": device in mappings,
            "network_valid": True,
        })
    for device, reason in rejected.items():
        result.append({
            "id": device,
            "short_id": "Not found",
            "has_short_id": False,
            "network_valid": False,
            "network_error": reason,
        })
    return result, rejected


def add_log(session_id, message):
    with sessions_lock:
        info = sessions.get(session_id)
        if not info:
            return
        logs = info.setdefault("logs", [])
        seq = logs[-1]["seq"] + 1 if logs else 1
        logs.append({"seq": seq, "time": time.strftime("%H:%M:%S"), "message": str(message)})
        if len(logs) > 500:
            del logs[:-500]


def report_result(test_name, device_id, short_id, result, duration, logs):
    if not SERVER_URL:
        return
    payload = json.dumps({
        "test_name": test_name,
        "device_id": device_id,
        "short_id": short_id,
        "status": result,
        "duration": duration,
        "logs": logs,
    }).encode("utf-8")
    try:
        req = urlrequest.Request(
            f"{SERVER_URL}/api/agent/result",
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "YTS-Linux-Agent"},
            method="POST",
        )
        with urlrequest.urlopen(req, timeout=15) as response:
            if response.status >= 300:
                logger.warning("Server result upload returned HTTP %s", response.status)
    except Exception as exc:
        logger.warning("Could not upload result to server: %s", exc)


def run_single(session_id, test_name, device_id, short_id, lock):
    started = time.monotonic()
    try:
        add_log(session_id, f"🚀 Starting {test_name}")
        add_log(session_id, f"📱 Device: {device_id} (Short ID: {short_id})")
        result = run_test(
            short_id,
            test_name,
            device_id,
            lambda message: add_log(session_id, message),
        )
        duration = round(time.monotonic() - started, 2)
        with sessions_lock:
            sessions[session_id]["status"] = "completed"
            sessions[session_id]["result"] = result
            sessions[session_id]["duration"] = duration
        report_result(test_name, device_id, short_id, result, duration, sessions[session_id]["logs"])
    except Exception as exc:
        duration = round(time.monotonic() - started, 2)
        logger.exception("Agent test failed")
        add_log(session_id, f"ERROR: {exc}")
        with sessions_lock:
            sessions[session_id]["status"] = "failed"
            sessions[session_id]["result"] = "FAILED"
            sessions[session_id]["duration"] = duration
        report_result(test_name, device_id, short_id, "FAILED", duration, sessions[session_id]["logs"])
    finally:
        lock.release()


def run_suite(session_id, test_names, device_id, short_id, lock):
    started = time.monotonic()
    results = {}
    try:
        for index, test_name in enumerate(test_names, 1):
            add_log(session_id, f"{'=' * 40}")
            add_log(session_id, f"▶️ Running [{index}/{len(test_names)}]: {test_name}")
            result = run_test(short_id, test_name, device_id, lambda message: add_log(session_id, message))
            results[test_name] = result
            with sessions_lock:
                sessions[session_id]["results"] = dict(results)
        passed = sum(value == "PASSED" for value in results.values())
        summary = f"{passed}/{len(test_names)} passed"
        duration = round(time.monotonic() - started, 2)
        with sessions_lock:
            sessions[session_id]["status"] = "completed"
            sessions[session_id]["result"] = summary
            sessions[session_id]["duration"] = duration
        for test_name, result in results.items():
            report_result(test_name, device_id, short_id, result, duration, sessions[session_id]["logs"])
    except Exception as exc:
        duration = round(time.monotonic() - started, 2)
        logger.exception("Agent suite failed")
        add_log(session_id, f"ERROR: {exc}")
        with sessions_lock:
            sessions[session_id]["status"] = "failed"
            sessions[session_id]["result"] = "FAILED"
            sessions[session_id]["duration"] = duration
    finally:
        lock.release()


@app.get("/api/health")
def health():
    devices, rejected = network_devices()
    return jsonify({
        "success": True,
        "agent": True,
        "platform": "Linux",
        "adb_installed": bool(find_adb()),
        "node_installed": check_node(),
        "yts_installed": check_yts_cli(),
        "device_count": len(devices),
        "rejected_device_count": len(rejected),
        "local_networks": local_ipv4_networks(),
        "server_connected": bool(SERVER_URL),
    })


@app.post("/api/discover-devices")
def api_discover():
    try:
        devices, rejected = discover_devices()
        return jsonify({"success": True, "devices": devices, "rejected": rejected})
    except Exception as exc:
        logger.exception("Agent discovery failed")
        return jsonify({"success": False, "error": str(exc)}), 500


@app.get("/api/device-details/<path:device_id>")
def api_device_details(device_id):
    ok, reason = validate_dut_network(device_id)
    if not ok:
        return jsonify({"success": False, "error": reason}), 400
    return jsonify({
        "success": True,
        "device_id": device_id,
        "details": get_device_details_cached(device_id),
    })


def validate_request(data):
    if not data:
        return "Request body must be valid JSON"
    test_name = data.get("test_name")
    device_id = data.get("device_id")
    short_id = data.get("short_id")
    if test_name not in YTS_TEST_COMMANDS:
        return "Unknown test name"
    if not device_id or not short_id or short_id == "Not found":
        return "A device and valid YTS short ID are required"
    ok, reason = validate_dut_network(device_id)
    if not ok:
        return reason
    if device_id not in check_adb_devices():
        return f"ADB device is not connected: {device_id}"
    mappings = discover_yts_devices()
    if mappings.get(device_id) != short_id:
        return f"YTS short ID does not match device {device_id}"
    return None


@app.post("/api/run-test")
def api_run_test():
    data = json_body()
    error = validate_request(data)
    if error:
        return jsonify({"success": False, "error": error}), 400
    device_id, short_id, test_name = data["device_id"], data["short_id"], data["test_name"]
    lock = get_device_lock(device_id)
    if not lock.acquire(blocking=False):
        return jsonify({"success": False, "error": f"Device {device_id} already has a running test"}), 409
    session_id = uuid.uuid4().hex
    with sessions_lock:
        sessions[session_id] = {
            "test_name": test_name, "device_id": device_id, "short_id": short_id,
            "status": "running", "result": None, "start_time": time.time(), "logs": [],
            "is_suite": False, "results": {},
        }
    threading.Thread(target=run_single, args=(session_id, test_name, device_id, short_id, lock), daemon=True).start()
    return jsonify({"success": True, "session_id": session_id})


@app.post("/api/run-suite")
def api_run_suite():
    data = json_body()
    if not data or not isinstance(data.get("test_names"), list) or not data["test_names"]:
        return jsonify({"success": False, "error": "No tests selected"}), 400
    for name in data["test_names"]:
        if name not in YTS_TEST_COMMANDS:
            return jsonify({"success": False, "error": f"Unknown test: {name}"}), 400
    error = validate_request({**data, "test_name": data["test_names"][0]})
    if error:
        return jsonify({"success": False, "error": error}), 400
    device_id, short_id = data["device_id"], data["short_id"]
    lock = get_device_lock(device_id)
    if not lock.acquire(blocking=False):
        return jsonify({"success": False, "error": f"Device {device_id} already has a running test"}), 409
    session_id = f"suite_{uuid.uuid4().hex}"
    with sessions_lock:
        sessions[session_id] = {
            "test_name": "Test Suite", "device_id": device_id, "short_id": short_id,
            "status": "running", "result": None, "start_time": time.time(), "logs": [],
            "is_suite": True, "results": {},
        }
    threading.Thread(target=run_suite, args=(session_id, data["test_names"], device_id, short_id, lock), daemon=True).start()
    return jsonify({"success": True, "session_id": session_id})


@app.get("/api/test-status/<session_id>")
def api_test_status(session_id):
    with sessions_lock:
        info = sessions.get(session_id)
        if not info:
            return jsonify({"success": False, "error": "Session not found"}), 404
        return jsonify({
            "success": True,
            "status": info["status"],
            "result": info.get("result"),
            "logs": list(info.get("logs", [])),
            "elapsed_time": time.time() - info["start_time"],
            "is_suite": info.get("is_suite", False),
            "results": dict(info.get("results", {})),
        })


@app.get("/api/test-commands")
def api_test_commands():
    return jsonify({"success": True, "tests": [
        {"name": name, "is_manual": name in YTS_MANUAL_TESTS,
         "wait_time": YTS_TEST_WAIT_SECONDS.get(name, 0),
         "instructions": TEST_INSTRUCTIONS.get(name, "No instructions available")}
        for name in YTS_TEST_COMMANDS
    ]})


@app.get("/api/test-categories")
def api_test_categories():
    return jsonify({"success": True, "categories": TEST_CATEGORIES})


if __name__ == "__main__":
    print(f"YTS Linux Agent listening on http://{HOST}:{PORT}")
    print(f"Allowed browser origins: {', '.join(ALLOWED_ORIGINS)}")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
