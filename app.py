#!/usr/bin/env python3
"""Linux-only Flask web server for the YTS Automation Tool."""
import os
import time
import uuid
import threading
import logging
import secrets
from pathlib import Path

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO

from yts_automation import (
    YTS_TEST_COMMANDS, YTS_MANUAL_TESTS, YTS_TEST_WAIT_SECONDS,
    TEST_INSTRUCTIONS, TEST_CATEGORIES, run_test, get_test_stats,
    get_recent_results, discover_yts_devices, check_adb_devices,
    check_node, check_yts_cli, get_device_details_cached,
    prepare_yts, cleanup_yts, find_adb
)

if os.name != "posix" or not hasattr(os, "uname") or os.uname().sysname != "Linux":
    raise SystemExit("ERROR: This application supports native Linux only.")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
allowed_origins = [x.strip() for x in os.environ.get(
    "ALLOWED_ORIGINS", "http://127.0.0.1:5000,http://localhost:5000"
).split(",") if x.strip()]
CORS(app, resources={r"/api/*": {"origins": allowed_origins}})
socketio = SocketIO(app, cors_allowed_origins=allowed_origins, async_mode="threading")

active_tests = {}
active_tests_lock = threading.RLock()
device_locks = {}
device_locks_lock = threading.Lock()
MAX_COMPLETED_SESSIONS = int(os.environ.get("MAX_COMPLETED_SESSIONS", "100"))
logger = logging.getLogger(__name__)
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(),
                    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")


def get_device_lock(device_id):
    with device_locks_lock:
        return device_locks.setdefault(device_id, threading.Lock())


def json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def validate_test_name(test_name):
    return isinstance(test_name, str) and test_name in YTS_TEST_COMMANDS


def validate_device_and_short_id(device_id, short_id):
    if not isinstance(device_id, str) or not device_id.strip():
        return "Missing device_id"
    if not isinstance(short_id, str) or not short_id.strip():
        return "Missing short_id"
    devices = check_adb_devices()
    if device_id not in devices:
        return f"ADB device is not connected: {device_id}"
    mapped = discover_yts_devices().get(device_id)
    if not mapped:
        return f"YTS short ID was not found for device: {device_id}"
    if mapped != short_id:
        return f"YTS short ID does not match device {device_id}"
    return None


def add_session_log(session_id, message):
    with active_tests_lock:
        info = active_tests.get(session_id)
        if not info:
            return
        logs = info.setdefault("logs", [])
        seq = (logs[-1]["seq"] + 1) if logs else 1
        logs.append({"seq": seq, "time": time.strftime("%H:%M:%S"), "message": str(message)})
        if len(logs) > 500:
            del logs[:-500]


def prune_completed_sessions():
    with active_tests_lock:
        if len(active_tests) <= MAX_COMPLETED_SESSIONS:
            return
        completed = sorted(
            ((sid, info.get("start_time", 0)) for sid, info in active_tests.items()
             if info.get("status") in {"completed", "failed"}),
            key=lambda x: x[1]
        )
        for sid, _ in completed[:max(0, len(active_tests) - MAX_COMPLETED_SESSIONS)]:
            active_tests.pop(sid, None)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/check-environment", methods=["GET"])
def check_environment():
    try:
        adb_path = find_adb()
        adb_ok = bool(adb_path)
        devices = check_adb_devices() if adb_ok else []
        return jsonify({
            "success": True,
            "node_installed": check_node(),
            "yts_installed": check_yts_cli(),
            "adb_installed": adb_ok,
            "adb_path": adb_path,
            "adb_platform": "Linux",
            "devices": devices,
            "device_count": len(devices),
        })
    except Exception as exc:
        logger.exception("Environment check failed")
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/discover-devices", methods=["POST"])
def discover_devices():
    try:
        shortid_map = discover_yts_devices()
        devices = check_adb_devices()
        device_info = [
            {"id": d, "short_id": shortid_map.get(d, "Not found"),
             "has_short_id": d in shortid_map} for d in devices
        ]
        return jsonify({"success": True, "devices": device_info, "shortid_map": shortid_map})
    except Exception as exc:
        logger.exception("Device discovery failed")
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/device-details/<path:device_id>", methods=["GET"])
def device_details(device_id):
    try:
        return jsonify({"success": True, "device_id": device_id,
                        "details": get_device_details_cached(device_id)})
    except Exception as exc:
        logger.exception("Device details failed")
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/test-commands", methods=["GET"])
def get_test_commands():
    return jsonify({"success": True, "tests": [
        {"name": name, "is_manual": name in YTS_MANUAL_TESTS,
         "wait_time": YTS_TEST_WAIT_SECONDS.get(name, 0),
         "instructions": TEST_INSTRUCTIONS.get(name, "No instructions available")}
        for name in YTS_TEST_COMMANDS
    ]})


@app.route("/api/test-categories", methods=["GET"])
def get_categories():
    return jsonify({"success": True, "categories": TEST_CATEGORIES})


@app.route("/api/test-stats", methods=["GET"])
def get_stats():
    try:
        return jsonify({"success": True, "stats": get_test_stats()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/test-instruction/<path:test_name>", methods=["GET"])
def get_test_instruction(test_name):
    if not validate_test_name(test_name):
        return jsonify({"success": False, "error": "Unknown test"}), 404
    return jsonify({
        "success": True, "test_name": test_name,
        "instruction": TEST_INSTRUCTIONS.get(test_name, "No instructions available"),
        "is_manual": test_name in YTS_MANUAL_TESTS,
        "wait_time": YTS_TEST_WAIT_SECONDS.get(test_name, 0)
    })


@app.route("/api/run-test", methods=["POST"])
def start_test():
    data = json_body()
    if data is None:
        return jsonify({"success": False, "error": "Request body must be valid JSON"}), 400
    test_name, device_id, short_id = data.get("test_name"), data.get("device_id"), data.get("short_id")
    if not validate_test_name(test_name):
        return jsonify({"success": False, "error": "Unknown test name"}), 400
    error = validate_device_and_short_id(device_id, short_id)
    if error:
        return jsonify({"success": False, "error": error}), 400
    lock = get_device_lock(device_id)
    if not lock.acquire(blocking=False):
        return jsonify({"success": False, "error": f"Device {device_id} already has a running test"}), 409
    session_id = uuid.uuid4().hex
    with active_tests_lock:
        active_tests[session_id] = {"test_name": test_name, "device_id": device_id,
                                     "short_id": short_id, "status": "running",
                                     "start_time": time.time(), "result": None, "logs": []}
    threading.Thread(target=run_test_async,
                     args=(session_id, short_id, test_name, device_id, lock),
                     name=f"yts-test-{session_id[:8]}", daemon=True).start()
    return jsonify({"success": True, "session_id": session_id,
                    "message": f'Test "{test_name}" started'})


@app.route("/api/run-suite", methods=["POST"])
def start_suite():
    data = json_body()
    if data is None:
        return jsonify({"success": False, "error": "Request body must be valid JSON"}), 400
    test_names, device_id, short_id = data.get("test_names", []), data.get("device_id"), data.get("short_id")
    if not isinstance(test_names, list) or not test_names:
        return jsonify({"success": False, "error": "No tests selected"}), 400
    invalid = [name for name in test_names if not validate_test_name(name)]
    if invalid:
        return jsonify({"success": False, "error": "Invalid tests", "invalid_tests": invalid}), 400
    error = validate_device_and_short_id(device_id, short_id)
    if error:
        return jsonify({"success": False, "error": error}), 400
    lock = get_device_lock(device_id)
    if not lock.acquire(blocking=False):
        return jsonify({"success": False, "error": f"Device {device_id} already has a running test"}), 409
    session_id = f"suite_{uuid.uuid4().hex}"
    with active_tests_lock:
        active_tests[session_id] = {"test_name": "Test Suite", "device_id": device_id,
                                     "short_id": short_id, "status": "running",
                                     "start_time": time.time(), "result": None, "logs": [],
                                     "is_suite": True, "tests": list(test_names), "results": {}}
    threading.Thread(target=run_suite_async,
                     args=(session_id, short_id, test_names, device_id, lock),
                     name=f"yts-suite-{session_id[-8:]}", daemon=True).start()
    return jsonify({"success": True, "session_id": session_id,
                    "message": f"Suite with {len(test_names)} tests started"})


@app.route("/api/test-status/<session_id>", methods=["GET"])
def get_test_status(session_id):
    with active_tests_lock:
        info = active_tests.get(session_id)
        if info is None:
            return jsonify({"success": False, "error": "Session not found"}), 404
        return jsonify({"success": True, "status": info["status"], "result": info.get("result"),
                        "logs": list(info.get("logs", [])),
                        "elapsed_time": time.time() - info["start_time"],
                        "is_suite": info.get("is_suite", False),
                        "results": dict(info.get("results", {}))})


@app.route("/api/test-results", methods=["GET"])
def get_test_results():
    try:
        return jsonify({"success": True, "results": get_recent_results(limit=100)})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/health", methods=["GET"])
def health_check():
    try:
        devices = check_adb_devices()
        components = {"node": check_node(), "yts": check_yts_cli(), "adb": bool(find_adb())}
        with active_tests_lock:
            active_count = sum(1 for x in active_tests.values() if x.get("status") == "running")
        return jsonify({"status": "healthy" if all(components.values()) else "degraded",
                        "timestamp": time.time(), "components": components,
                        "device_count": len(devices), "active_tests": active_count})
    except Exception:
        logger.exception("Health check failed")
        return jsonify({"status": "unhealthy", "timestamp": time.time()}), 500


def run_test_async(session_id, short_id, test_name, device_id, device_lock):
    try:
        result = run_test(short_id, test_name, device_id, lambda msg: add_session_log(session_id, msg))
        with active_tests_lock:
            if session_id in active_tests:
                active_tests[session_id]["status"] = "completed"
                active_tests[session_id]["result"] = result
        socketio.emit("test_completed", {"session_id": session_id, "result": result})
    except Exception as exc:
        logger.exception("Test worker failed: %s", session_id)
        with active_tests_lock:
            if session_id in active_tests:
                active_tests[session_id]["status"] = "failed"
                active_tests[session_id]["result"] = "FAILED"
        add_session_log(session_id, f"ERROR: {exc}")
        socketio.emit("test_error", {"session_id": session_id, "error": str(exc)})
    finally:
        device_lock.release()
        prune_completed_sessions()


def run_suite_async(session_id, short_id, test_names, device_id, device_lock):
    try:
        results = {}
        passed = 0
        callback = lambda msg: add_session_log(session_id, msg)
        for index, test_name in enumerate(test_names, 1):
            callback(f"\n{'=' * 40}")
            callback(f"▶️ Running [{index}/{len(test_names)}]: {test_name}")
            callback(f"{'=' * 40}")
            result = run_test(short_id, test_name, device_id, callback)
            results[test_name] = result
            passed += result == "PASSED"
            with active_tests_lock:
                if session_id in active_tests:
                    active_tests[session_id]["results"] = dict(results)
        failed = len(test_names) - passed
        summary = f"{passed}/{len(test_names)} passed"
        callback(f"\n{'=' * 40}\n📊 SUITE COMPLETE\nTotal: {len(test_names)} | ✅ Passed: {passed} | ❌ Failed: {failed} | 📈 Rate: {round(passed * 100 / len(test_names), 1)}%\n{'=' * 40}")
        with active_tests_lock:
            if session_id in active_tests:
                active_tests[session_id]["status"] = "completed"
                active_tests[session_id]["result"] = summary
        socketio.emit("test_completed", {"session_id": session_id, "result": summary, "results": results})
    except Exception as exc:
        logger.exception("Suite worker failed: %s", session_id)
        with active_tests_lock:
            if session_id in active_tests:
                active_tests[session_id]["status"] = "failed"
                active_tests[session_id]["result"] = "FAILED"
        add_session_log(session_id, f"ERROR: {exc}")
        socketio.emit("test_error", {"session_id": session_id, "error": str(exc)})
    finally:
        device_lock.release()
        prune_completed_sessions()


def main():
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    print("\n" + "=" * 50)
    print("  🚀 YTS Automation Web Interface")
    print("  Linux-only | Runtime YTS")
    print("=" * 50)
    try:
        yts_path = prepare_yts()
        print(f"YTS ready: {yts_path}")
    except Exception as exc:
        logger.exception("YTS startup preparation failed")
        print(f"ERROR: Could not prepare YTS CLI: {exc}")
        cleanup_yts()
        raise SystemExit(1)
    print(f"Starting web server on http://{host}:{port}")
    print("YTS is temporary for this application run and is removed on exit.")
    try:
        socketio.run(app, debug=False, host=host, port=port)
    finally:
        cleanup_yts()


if __name__ == "__main__":
    main()
