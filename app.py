#!/usr/bin/env python3
"""
Flask web server for YTS Automation Tool
"""
import os
import time
import uuid
import threading
import logging

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO

# Optional Node.js paths.
# Override these using environment variables when required.
node_path = os.environ.get(
    "NODE_PATH",
    r"C:\Program Files\nodejs"
)
npm_path = os.environ.get(
    "NPM_PATH",
    os.path.expanduser(r"~\AppData\Roaming\npm")
)

if os.path.isdir(node_path):
    os.environ["PATH"] = (
        f"{node_path};"
        f"{npm_path};"
        f"{os.environ.get('PATH', '')}"
    )

# Import the automation logic
from yts_automation import (
    YTS_TEST_COMMANDS, YTS_MANUAL_TESTS, YTS_TEST_WAIT_SECONDS,
    TEST_INSTRUCTIONS, TEST_CATEGORIES,
    run_test, run_test_suite, get_test_stats, get_recent_results,
    discover_yts_devices, check_adb_devices, check_node, check_yts_cli,
    get_device_details_cached, get_test_categories, prepare_yts, cleanup_yts
)
from adb_platform import get_adb_info

app = Flask(__name__)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "change-this-secret-key"
)

allowed_origins = os.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:5000"
).split(",")

CORS(
    app,
    resources={
        r"/api/*": {
            "origins": allowed_origins
        }
    }
)

socketio = SocketIO(
    app,
    cors_allowed_origins=allowed_origins,
    async_mode="threading"
)

# Active test state is process-local because this application controls physical ADB devices from one workstation.
active_tests = {}
active_tests_lock = threading.RLock()
device_locks = {}
device_locks_lock = threading.Lock()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)


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
    if device_id not in check_adb_devices():
        return f"ADB device is not connected: {device_id}"
    discovered = discover_yts_devices()
    mapped = discovered.get(device_id)
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
        info.setdefault("logs", []).append({
            "time": time.strftime("%H:%M:%S"),
            "message": str(message)
        })
        if len(info["logs"]) > 500:
            info["logs"] = info["logs"][-500:]

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/check-environment', methods=['GET'])
def check_environment():
    try:
        node_ok = check_node()
        yts_ok = check_yts_cli()
        devices = check_adb_devices()
        adb_info = get_adb_info()

        return jsonify({
            'success': True,
            'node_installed': node_ok,
            'yts_installed': yts_ok,
            'adb_installed': adb_info.get('available', False),
            'adb_path': adb_info.get('path'),
            'adb_platform': adb_info.get('platform'),
            'adb_error': adb_info.get('error'),
            'devices': devices,
            'device_count': len(devices)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/discover-devices', methods=['POST'])
def discover_devices():
    try:
        shortid_map = discover_yts_devices()
        devices = check_adb_devices()
        
        device_info = []
        for device in devices:
            info = {
                'id': device,
                'short_id': shortid_map.get(device, 'Not found'),
                'has_short_id': device in shortid_map
            }
            device_info.append(info)
        
        return jsonify({
            'success': True,
            'devices': device_info,
            'shortid_map': shortid_map
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/device-details/<device_id>', methods=['GET'])
def device_details(device_id):
    try:
        details = get_device_details_cached(device_id)
        return jsonify({
            'success': True,
            'device_id': device_id,
            'details': details
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/test-commands', methods=['GET'])
def get_test_commands():
    tests = []
    for name in YTS_TEST_COMMANDS:
        tests.append({
            'name': name,
            'is_manual': name in YTS_MANUAL_TESTS,
            'wait_time': YTS_TEST_WAIT_SECONDS.get(name, 0),
            'instructions': TEST_INSTRUCTIONS.get(name, 'No instructions available')
        })
    return jsonify({'success': True, 'tests': tests})

@app.route('/api/test-categories', methods=['GET'])
def get_categories():
    return jsonify({'success': True, 'categories': TEST_CATEGORIES})

@app.route('/api/test-stats', methods=['GET'])
def get_stats():
    try:
        stats = get_test_stats()
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/test-instruction/<test_name>', methods=['GET'])
def get_test_instruction(test_name):
    if not validate_test_name(test_name):
        return jsonify({'success': False, 'error': 'Unknown test'}), 404
    return jsonify({
        'success': True,
        'test_name': test_name,
        'instruction': TEST_INSTRUCTIONS.get(test_name, 'No instructions available'),
        'is_manual': test_name in YTS_MANUAL_TESTS,
        'wait_time': YTS_TEST_WAIT_SECONDS.get(test_name, 0)
    })

@app.route('/api/run-test', methods=['POST'])
def start_test():
    data = json_body()
    if data is None:
        return jsonify({'success': False, 'error': 'Request body must be valid JSON'}), 400
    test_name, device_id, short_id = data.get('test_name'), data.get('device_id'), data.get('short_id')
    if not validate_test_name(test_name):
        return jsonify({'success': False, 'error': 'Unknown test name'}), 400
    error = validate_device_and_short_id(device_id, short_id)
    if error:
        return jsonify({'success': False, 'error': error}), 400
    device_lock = get_device_lock(device_id)
    if not device_lock.acquire(blocking=False):
        return jsonify({'success': False, 'error': f'Device {device_id} already has a running test'}), 409
    session_id = uuid.uuid4().hex
    with active_tests_lock:
        active_tests[session_id] = {
            'test_name': test_name, 'device_id': device_id, 'short_id': short_id,
            'status': 'running', 'start_time': time.time(), 'result': None, 'logs': []
        }
    threading.Thread(
        target=run_test_async,
        args=(session_id, short_id, test_name, device_id, device_lock),
        name=f'yts-test-{session_id[:8]}', daemon=True
    ).start()
    return jsonify({'success': True, 'session_id': session_id, 'message': f'Test "{test_name}" started'})

@app.route('/api/run-suite', methods=['POST'])
def start_suite():
    data = json_body()
    if data is None:
        return jsonify({'success': False, 'error': 'Request body must be valid JSON'}), 400
    test_names, device_id, short_id = data.get('test_names', []), data.get('device_id'), data.get('short_id')
    if not isinstance(test_names, list) or not test_names:
        return jsonify({'success': False, 'error': 'No tests selected'}), 400
    invalid = [name for name in test_names if not validate_test_name(name)]
    if invalid:
        return jsonify({'success': False, 'error': 'One or more invalid tests selected', 'invalid_tests': invalid}), 400
    error = validate_device_and_short_id(device_id, short_id)
    if error:
        return jsonify({'success': False, 'error': error}), 400
    device_lock = get_device_lock(device_id)
    if not device_lock.acquire(blocking=False):
        return jsonify({'success': False, 'error': f'Device {device_id} already has a running test'}), 409
    session_id = f"suite_{uuid.uuid4().hex}"
    with active_tests_lock:
        active_tests[session_id] = {
            'test_name': 'Test Suite', 'device_id': device_id, 'short_id': short_id,
            'status': 'running', 'start_time': time.time(), 'result': None, 'logs': [],
            'is_suite': True, 'tests': list(test_names), 'results': {}
        }
    threading.Thread(
        target=run_suite_async,
        args=(session_id, short_id, test_names, device_id, device_lock),
        name=f'yts-suite-{session_id[-8:]}', daemon=True
    ).start()
    return jsonify({'success': True, 'session_id': session_id, 'message': f'Suite with {len(test_names)} tests started'})

@app.route('/api/test-status/<session_id>', methods=['GET'])
def get_test_status(session_id):
    with active_tests_lock:
        info = active_tests.get(session_id)
        if info is None:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        return jsonify({
            'success': True, 'status': info['status'], 'result': info.get('result'),
            'logs': list(info.get('logs', [])), 'elapsed_time': time.time() - info['start_time'],
            'is_suite': info.get('is_suite', False), 'results': dict(info.get('results', {}))
        })

@app.route('/api/test-results', methods=['GET'])
def get_test_results():
    try:
        results = get_recent_results(limit=100)
        return jsonify({'success': True, 'results': results})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    try:
        devices = check_adb_devices()
        components = {'node': check_node(), 'yts': check_yts_cli(), 'adb': bool(devices)}
        with active_tests_lock:
            active_count = len(active_tests)
        return jsonify({
            'status': 'healthy' if all(components.values()) else 'degraded',
            'timestamp': time.time(), 'components': components,
            'device_count': len(devices), 'active_tests': active_count
        })
    except Exception:
        logger.exception('Health check failed')
        return jsonify({'status': 'unhealthy', 'timestamp': time.time()}), 500

def run_test_async(session_id, short_id, test_name, device_id, device_lock):
    try:
        result = run_test(short_id, test_name, device_id, lambda msg: add_session_log(session_id, msg))
        with active_tests_lock:
            if session_id in active_tests:
                active_tests[session_id]['status'] = 'completed'
                active_tests[session_id]['result'] = result
        socketio.emit('test_completed', {'session_id': session_id, 'result': result})
    except Exception as exc:
        logger.exception('Test worker failed: %s', session_id)
        with active_tests_lock:
            if session_id in active_tests:
                active_tests[session_id]['status'] = 'failed'
                active_tests[session_id]['result'] = 'FAILED'
        add_session_log(session_id, f'ERROR: {exc}')
        socketio.emit('test_error', {'session_id': session_id, 'error': str(exc)})
    finally:
        device_lock.release()


def run_suite_async(session_id, short_id, test_names, device_id, device_lock):
    try:
        results, passed, failed = {}, 0, 0
        log_callback = lambda msg: add_session_log(session_id, msg)
        total = len(test_names)
        for index, test_name in enumerate(test_names, 1):
            log_callback(f"\n{'=' * 40}")
            log_callback(f"▶️ Running [{index}/{total}]: {test_name}")
            log_callback(f"{'=' * 40}")
            result = run_test(short_id, test_name, device_id, log_callback)
            results[test_name] = result
            if result == 'PASSED': passed += 1
            else: failed += 1
            with active_tests_lock:
                if session_id in active_tests:
                    active_tests[session_id]['results'] = dict(results)
        summary = f"{passed}/{total} passed"
        log_callback(f"\n{'=' * 40}\n📊 SUITE COMPLETE\nTotal: {total} | ✅ Passed: {passed} | ❌ Failed: {failed} | 📈 Rate: {round(passed * 100 / total, 1)}%\n{'=' * 40}")
        with active_tests_lock:
            if session_id in active_tests:
                active_tests[session_id]['status'] = 'completed'
                active_tests[session_id]['result'] = summary
        socketio.emit('test_completed', {'session_id': session_id, 'result': summary, 'results': results})
    except Exception as exc:
        logger.exception('Suite worker failed: %s', session_id)
        with active_tests_lock:
            if session_id in active_tests:
                active_tests[session_id]['status'] = 'failed'
                active_tests[session_id]['result'] = 'FAILED'
        add_session_log(session_id, f'ERROR: {exc}')
        socketio.emit('test_error', {'session_id': session_id, 'error': str(exc)})
    finally:
        device_lock.release()


def main():
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '5000'))
    print("\n" + "=" * 50)
    print("  🚀 YTS Automation Web Interface")
    print("  Version 2.2 - Runtime YTS Download")
    print("=" * 50)
    print("\nPreparing YTS CLI (fresh download for this run)...")
    try:
        yts_path = prepare_yts()
        print(f"YTS ready: {yts_path}")
    except Exception as exc:
        logger.exception("YTS startup preparation failed")
        print(f"\nERROR: Could not prepare YTS CLI: {exc}")
        cleanup_yts()
        raise SystemExit(1)

    print(f"\nStarting web server on http://{host}:{port}")
    print("YTS is stored only in a temporary directory for this run.")
    print("It will be removed automatically when the application exits.")
    print("Press Ctrl+C to stop\n")
    try:
        socketio.run(app, debug=False, host=host, port=port)
    finally:
        cleanup_yts()


if __name__ == '__main__':
    main()
