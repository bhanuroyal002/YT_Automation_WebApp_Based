#!/usr/bin/env python3
"""
YTS Automation Script - Linux-only web integration.
"""
import os
import re
import datetime
import time
import shutil
import subprocess
import tempfile
import zipfile
import urllib.request
import atexit
import signal
import sqlite3
import threading
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

# ============================================
# Linux-native ADB helpers
# ============================================

def find_adb() -> Optional[str]:
    configured = os.environ.get("ADB_PATH", "").strip()
    candidates = []
    if configured:
        candidates.append(configured)
    candidates.extend(["/usr/bin/adb", "/usr/local/bin/adb"])
    which = shutil.which("adb")
    if which:
        candidates.append(which)

    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen or not os.path.isfile(candidate):
            continue
        seen.add(candidate)
        try:
            result = subprocess.run(
                [candidate, "version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", timeout=10, check=False
            )
            if result.returncode == 0 and "Android Debug Bridge" in result.stdout:
                return candidate
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def adb_command(*args: str) -> list[str]:
    adb = find_adb()
    if not adb:
        raise RuntimeError("Native Linux ADB was not found. Install android-tools-adb or set ADB_PATH.")
    return [adb, *args]


def ensure_network_device(device: Optional[str]):
    if not device:
        return True, ""
    try:
        result = subprocess.run(
            adb_command("connect", device), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", timeout=15, check=False
        )
        output = (result.stdout or "").strip()
        low = output.lower()
        return result.returncode == 0 and ("connected to" in low or "already connected" in low), output
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)


def get_adb_info():
    adb = find_adb()
    if not adb:
        return {"available": False, "path": None, "platform": "Linux",
                "version": None, "error": "No working native Linux ADB client found"}
    try:
        result = subprocess.run(
            [adb, "version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", timeout=10, check=False
        )
        output = result.stdout or ""
        return {"available": result.returncode == 0, "path": adb, "platform": "Linux",
                "version": output.splitlines()[0] if output else None,
                "error": None if result.returncode == 0 else output.strip()}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "path": adb, "platform": "Linux", "version": None, "error": str(exc)}


# ============================================
# Constants and runtime YTS
# ============================================
CACHE_TIMEOUT = 60
MAX_RETRIES = 2
TEST_TIMEOUT = 300
MAX_LOG_SIZE_MB = 10
_device_cache = {}
_cache_timestamps = {}
YTS_DOWNLOAD_URL = os.environ.get("YTS_DOWNLOAD_URL", "http://yts.devicecertification.youtube/yts_server.zip")
YTS_DOWNLOAD_TIMEOUT = int(os.environ.get("YTS_DOWNLOAD_TIMEOUT", "120"))
_yts_runtime_dir = None
_yts_script_path = None
_yts_prepare_lock = threading.Lock()
_yts_processes = set()
_yts_processes_lock = threading.Lock()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_PATH = DATA_DIR / "test_results.db"
LOG_PATH = DATA_DIR / "test_results.log"

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)


@contextmanager
def get_db():
    conn = sqlite3.connect(str(DATABASE_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS test_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_name TEXT NOT NULL,
            device_id TEXT,
            short_id TEXT,
            status TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            duration INTEGER,
            logs TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS test_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_name TEXT UNIQUE,
            total_runs INTEGER DEFAULT 0,
            passes INTEGER DEFAULT 0,
            failures INTEGER DEFAULT 0,
            avg_duration REAL DEFAULT 0
        )''')
        conn.commit()


def save_result_db(test_name, status, device_id=None, short_id=None, duration=None, logs=None):
    try:
        with get_db() as conn:
            conn.execute(
                'INSERT INTO test_results (test_name, device_id, short_id, status, duration, logs) VALUES (?, ?, ?, ?, ?, ?)',
                (test_name, device_id, short_id, status, duration, logs)
            )
            row = conn.execute(
                'SELECT total_runs, passes, failures, avg_duration FROM test_metrics WHERE test_name = ?',
                (test_name,)
            ).fetchone()
            if row:
                total = row['total_runs'] + 1
                passes = row['passes'] + (1 if status == 'PASSED' else 0)
                failures = row['failures'] + (1 if status == 'FAILED' else 0)
                average = ((row['avg_duration'] * row['total_runs']) + (duration or 0)) / total
                conn.execute(
                    'UPDATE test_metrics SET total_runs=?, passes=?, failures=?, avg_duration=? WHERE test_name=?',
                    (total, passes, failures, average, test_name)
                )
            else:
                conn.execute(
                    'INSERT INTO test_metrics (test_name,total_runs,passes,failures,avg_duration) VALUES (?,1,?,?,?)',
                    (test_name, 1 if status == 'PASSED' else 0, 1 if status == 'FAILED' else 0, duration or 0)
                )
            conn.commit()
    except Exception:
        logger.exception("Failed to save result for %s", test_name)


def get_results_db(limit=100):
    with get_db() as conn:
        return [dict(row) for row in conn.execute(
            'SELECT * FROM test_results ORDER BY timestamp DESC LIMIT ?', (limit,)
        ).fetchall()]


def get_stats_db():
    with get_db() as conn:
        return [dict(row) for row in conn.execute('''
            SELECT test_name,total_runs,passes,failures,ROUND(avg_duration,2) AS avg_duration,
                   ROUND(passes*100.0/total_runs,1) AS pass_rate
            FROM test_metrics ORDER BY total_runs DESC
        ''').fetchall()]


def rotate_log_file(log_file=None, max_size_mb=10):
    path = Path(log_file) if log_file else LOG_PATH
    if path.exists() and path.stat().st_size > max_size_mb * 1024 * 1024:
        backup = path.with_name(f"{path.name}.{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.bak")
        try:
            path.replace(backup)
            return True
        except OSError:
            logger.exception("Failed to rotate log file %s", path)
    return False


# ============================================
# Test configuration — original commands preserved
# ============================================
YTS_TEST_COMMANDS = {
    "LiveDRM": 'yts launch {shortId} https://www.youtube.com/tv?list=OLAK5uy_mKAu6VNK3gMSq_L8fU_C6myQnuuuIzvWY',
    "12 Hour Endurance": 'yts test {shortId} --test-version=20250415 "In-app Video Endurance"',
    "YouTube Music Endurance": 'yts launch {shortId} https://www.youtube.com/tv#/watch?v=13EL6Mgeocc',
    "Persistence Cookie 200 times": 'yts test {shortId} --test-version=20250415 "Persistence Cookie keeps cookie intact after 200 times of device on/off"',
    "Live streaming": 'yts launch {shortId} "https://www.youtube.com/tv?c=UC4R8DWoMoI7CAwX8_LjQHig"',
    "Adaptive Bit Rate": 'yts test {shortId} --test-version=20250415 --guided "Media Adaptive Bit Rate"',
    "Adaptive Bit Rate - DRM": 'yts test {shortId} --test-version=20250415 --guided "DRM DRM"',
    "21:9 Aspect Ratio": 'yts test {shortId} --test-version=20250415 --guided "In-app 21:9 Aspect Ratio"',
    "4:3 Aspect Ratio": 'yts test {shortId} --test-version=20250415 --guided "In-app 4:3 Aspect Ratio"',
    "16:9 Aspect Ratio": 'yts test {shortId} --test-version=20250415 --guided "In-app 16:9 Aspect Ratio"',
    "17:30 Aspect Ratio": 'yts test {shortId} --test-version=20250415 --guided "In-app 17:30 Aspect Ratio"',
    "[Voice&Search] Soft-mic Button": 'yts launch {shortId}',
    "Current Time": 'yts launch {shortId} "https://www.youtube.com/tv?env_showUIStats=true&use_toa=true&v=RgodTgI2EDo"',
    "Params Remote": 'yts test {shortId} --test-version=20250415 --guided "Params Remote"',
    "System-wide Exit Key": 'yts test {shortId} --test-version=20250415 --guided "In-app System-wide Exit Key"',
    "Resizing": 'yts test {shortId} --test-version=20250415 --guided "Media Resizing 2024+"',
    "Alternate Time Zone": 'yts test {shortId} --test-version=20250415 --guided "Time Alternate Time Zones"',
    "TTS": 'yts test {shortId} --test-version=20250415 --guided "Speech TTS"',
    "Required If Unreserved": 'yts test {shortId} --test-version=20250415 --guided "Key Event Required If Unreserved 2024+"',
    "Localization": 'yts test {shortId} --test-version=20250415 --guided "ETC Localization"',
    "Screensaver": 'yts test {shortId} --test-version=20250415 --guided "ETC Page Visibility Screensaver"',
    "High Contrast Text Setting": 'yts test {shortId} --test-version=20250415 --guided "ETC High Contrast Text"',
    "TTS Setting": 'yts test {shortId} --test-version=20250415 --guided "ETC TTS"',
    "Animated WebP": 'yts test {shortId} --test-version=20250415 --guided "ETC Animated WebP"',
    "Non-animated WebP": 'yts test {shortId} --test-version=20250415 --guided "ETC Non-animated WebP"',
    "Fonts": 'yts test {shortId} --test-version=20250415 --guided "ETC Fonts"',
    "Page Visibility Overlay": 'yts test {shortId} --test-version=20250415 --guided "ETC Page Visibility Overlay"',
    "Language Setting": 'yts test {shortId} --test-version=20250415 --guided "ETC Language"',
    "Captions": 'yts test {shortId} --test-version=20250415 --guided "ETC Captions"',
    "Params Menu": 'yts test {shortId} --test-version=20250415 --guided "Params Menu"',
    "In-app HDR HLG": 'yts launch {shortId} https://www.youtube.com/tv?v=5w58p6iVhPc',
    "In-app HDR PQ": 'yts launch {shortId} https://www.youtube.com/tv?v=Ss75O8yllyc',
    "In-app Visual Audio / Video Sync": 'yts launch {shortId} "https://www.youtube.com/tv?list=PLT2JIu9jdshqNyrN5gzxaihngAjwFOFMB"',
    "DRM Purchased Movie": 'yts launch {shortId} https://www.youtube.com/tv?v=MeFoUwes8nE',
    "Multi-App Performance": 'yts launch {shortId} https://www.youtube.com/tv?automationRoutine=certPerformanceRoutine&samples=100&use_toa=true&hl=en-US&gl=en_US',
    "System Overlay": 'yts launch {shortId} https://www.youtube.com/tv?automationRoutine=certPerformanceRoutine&samples=16&use_toa=true&hl=en-US&gl=en_US',
    "Sign-in Persistence": 'yts launch {shortId}'
}

YTS_MANUAL_TESTS = {
    "LiveDRM", "In-app HDR HLG", "In-app HDR PQ", "In-app Visual Audio / Video Sync",
    "DRM Purchased Movie", "Multi-App Performance", "System Overlay",
    "YouTube Music Endurance", "Live streaming"
}
YTS_TEST_WAIT_SECONDS = {
    "LiveDRM": 1080, "In-app HDR HLG": 300, "In-app HDR PQ": 300,
    "YouTube Music Endurance": 310, "Live streaming": 43200
}
TEST_CATEGORIES = {
    "Media Tests": ["Adaptive Bit Rate", "Adaptive Bit Rate - DRM", "Resizing"],
    "Aspect Ratio Tests": ["21:9 Aspect Ratio", "4:3 Aspect Ratio", "16:9 Aspect Ratio", "17:30 Aspect Ratio"],
    "ETC Tests": ["Fonts", "Captions", "Localization", "TTS", "Screensaver", "High Contrast Text Setting", "TTS Setting", "Animated WebP", "Non-animated WebP", "Page Visibility Overlay", "Language Setting"],
    "Manual Tests": ["LiveDRM", "YouTube Music Endurance", "Live streaming"],
    "Performance Tests": ["Multi-App Performance", "System Overlay"],
    "HDR Tests": ["In-app HDR HLG", "In-app HDR PQ"],
    "Launch Tests": ["In-app Visual Audio / Video Sync", "DRM Purchased Movie", "Sign-in Persistence"],
    "Guided Tests": ["Params Remote", "System-wide Exit Key", "Alternate Time Zone", "Params Menu"],
    "Endurance Tests": ["12 Hour Endurance", "Persistence Cookie 200 times"],
    "Voice Tests": ["[Voice&Search] Soft-mic Button"],
    "Time Tests": ["Current Time"]
}

# Keep the instructions keyed to every test. Detailed entries can be expanded without changing the API.
TEST_INSTRUCTIONS = {name: "Follow the on-screen YTS instructions for this test and verify the documented pass/fail criteria." for name in YTS_TEST_COMMANDS}
TEST_INSTRUCTIONS["Adaptive Bit Rate"] = "Follow on-screen instructions.\n\nPass/Fail Criteria:\n- Starts at low resolution → adapts upward\n- Smooth transition\n- No stutter, skip, or pause\n- May pass even if it doesn't reach the maximum resolution"
TEST_INSTRUCTIONS["12 Hour Endurance"] = "Run the test and let it run for 12 hours.\n\nPass/Fail Criteria:\n- Device must continuously play for 12 hours without stopping\n- No crashes or interruptions"
TEST_INSTRUCTIONS["LiveDRM"] = "Verify the launched video has a LIVE badge and enable Stats for Nerds. Observe playback for 18 minutes.\n\nPass/Fail Criteria:\n- 'Live Latency' and 'Live Mode' fields must appear\n- 'Protected' must include WVA\n- Dropped frames ≤ 0.5%\n- No green/magenta corruption, skipping, stuttering, or buffering"

# ============================================
# Runtime YTS lifecycle
# ============================================
def _safe_extract_zip(zip_path: Path, extract_dir: Path):
    extract_dir.mkdir(parents=True, exist_ok=True)
    root = extract_dir.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (extract_dir / member.filename).resolve()
            if os.path.commonpath([str(root), str(target)]) != str(root):
                raise RuntimeError(f"Unsafe YTS archive member: {member.filename}")
        archive.extractall(extract_dir)


def _locate_yts(root: Path) -> Optional[Path]:
    # Prefer the native executable, then yts.js as a fallback for packages where the launcher is script-based.
    for candidate in root.rglob("yts"):
        if candidate.is_file():
            try:
                candidate.chmod(candidate.stat().st_mode | 0o111)
            except OSError:
                pass
            return candidate
    for candidate in root.rglob("yts.js"):
        if candidate.is_file():
            return candidate
    return None


def prepare_yts() -> str:
    global _yts_runtime_dir, _yts_script_path
    with _yts_prepare_lock:
        if _yts_script_path and Path(_yts_script_path).exists():
            return _yts_script_path
        runtime = Path(tempfile.mkdtemp(prefix="yts_automation_"))
        zip_path = runtime / "yts_server.zip"
        extract_dir = runtime / "package"
        logger.info("Downloading YTS CLI from %s", YTS_DOWNLOAD_URL)
        try:
            request = urllib.request.Request(YTS_DOWNLOAD_URL, headers={"User-Agent": "YTS-Automation-WebApp"})
            with urllib.request.urlopen(request, timeout=YTS_DOWNLOAD_TIMEOUT) as response, open(zip_path, "wb") as out:
                shutil.copyfileobj(response, out)
            _safe_extract_zip(zip_path, extract_dir)
            launcher = _locate_yts(extract_dir)
            if not launcher:
                raise RuntimeError("Downloaded YTS package does not contain a usable yts/yts.js launcher")
            _yts_runtime_dir = runtime
            _yts_script_path = str(launcher)
            return _yts_script_path
        except Exception:
            shutil.rmtree(runtime, ignore_errors=True)
            raise


def _yts_command(*args: str) -> list[str]:
    launcher = prepare_yts()
    if launcher.endswith(".js"):
        return ["node", launcher, *args]
    return [launcher, *args]


def _run_command(command, timeout=TEST_TIMEOUT, log_callback=None):
    env = os.environ.copy()
    adb = find_adb()
    if adb:
        env["PATH"] = f"{Path(adb).parent}:{env.get('PATH', '')}"
        env["ADB_PATH"] = adb
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", bufsize=1, env=env
    )
    with _yts_processes_lock:
        _yts_processes.add(process)
    lines = []
    start = time.time()
    try:
        while True:
            line = process.stdout.readline() if process.stdout else ""
            if line:
                line = line.rstrip("\n")
                lines.append(line)
                if log_callback:
                    log_callback(line)
            elif process.poll() is not None:
                break
            elif time.time() - start > timeout:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                if log_callback:
                    log_callback(f"ERROR: Command timed out after {timeout} seconds")
                break
        return process.wait(timeout=10), lines
    finally:
        with _yts_processes_lock:
            _yts_processes.discard(process)


def cleanup_yts():
    global _yts_runtime_dir, _yts_script_path
    with _yts_processes_lock:
        processes = list(_yts_processes)
    for process in processes:
        try:
            if process.poll() is None:
                process.terminate()
        except Exception:
            pass
    for process in processes:
        try:
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
    if _yts_runtime_dir:
        shutil.rmtree(_yts_runtime_dir, ignore_errors=True)
    _yts_runtime_dir = None
    _yts_script_path = None

atexit.register(cleanup_yts)
for _sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
    if _sig:
        try:
            signal.signal(_sig, lambda *_: cleanup_yts())
        except Exception:
            pass

# ============================================
# ADB / Node / YTS operations
# ============================================
def check_adb_devices():
    target = os.environ.get("ADB_DEVICE", "").strip()
    if target:
        ok, message = ensure_network_device(target)
        if not ok:
            logger.warning("ADB connect failed for %s: %s", target, message)
    result = subprocess.run(
        adb_command("devices"), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", timeout=15, check=False
    )
    devices = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] in {"device", "offline", "unauthorized"}:
            devices.append(parts[0])
    return devices


def discover_yts_devices():
    rc, lines = _run_command(_yts_command("discover"), timeout=60)
    mapping = {}
    for line in lines:
        # Common YTS form: (short-id) ... (adb: SERIAL)
        short_match = re.search(r"^\s*\(([^)]+)\)", line)
        adb_match = re.search(r"adb:\s*([^\s)]+)", line)
        if short_match and adb_match:
            mapping[adb_match.group(1)] = short_match.group(1)
    return mapping


def check_node():
    try:
        result = subprocess.run(["node", "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=10, check=False)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def check_yts_cli():
    try:
        rc, _ = _run_command(_yts_command("--help"), timeout=30)
        return rc == 0
    except Exception:
        logger.exception("YTS CLI check failed")
        return False


def get_device_details_cached(device_id):
    now = time.time()
    if device_id in _device_cache and now - _cache_timestamps.get(device_id, 0) < CACHE_TIMEOUT:
        return _device_cache[device_id]
    keys = {
        "model": "ro.product.model",
        "manufacturer": "ro.product.manufacturer",
        "android_version": "ro.build.version.release",
        "security_patch": "ro.build.version.security_patch",
        "product": "ro.product.name",
        "fingerprint": "ro.build.fingerprint",
    }
    details = {}
    for name, prop in keys.items():
        try:
            result = subprocess.run(adb_command("-s", device_id, "shell", "getprop", prop),
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                    timeout=10, check=False)
            details[name] = result.stdout.strip() or "Unknown"
        except Exception:
            details[name] = "Unknown"
    _device_cache[device_id] = details
    _cache_timestamps[device_id] = now
    return details


def _build_yts_args(short_id, test_name):
    import shlex
    template = YTS_TEST_COMMANDS.get(test_name)
    if not template:
        raise ValueError(f"Unknown test: {test_name}")
    parts = shlex.split(template.format(shortId=short_id))
    if parts and parts[0] == "yts":
        parts = parts[1:]
    return parts


def _detect_result(lines):
    for line in reversed(lines):
        upper = line.upper()
        if "RESULT: PASSED" in upper or "✓ PASSED" in upper:
            return "PASSED"
        if "RESULT: FAILED" in upper or "✗ FAILED" in upper:
            return "FAILED"
    return None


def run_test(short_id, test_name, device_id=None, log_callback=None):
    start = time.time()
    logs = []
    try:
        command = _yts_command(*_build_yts_args(short_id, test_name))
        if log_callback:
            log_callback("Executing: " + " ".join(command))
        timeout = max(TEST_TIMEOUT, YTS_TEST_WAIT_SECONDS.get(test_name, 0) + 300)
        rc, logs = _run_command(command, timeout=timeout, log_callback=log_callback)
        result = _detect_result(logs) or ("PASSED" if rc == 0 else "FAILED")
    except Exception as exc:
        if log_callback:
            log_callback(f"ERROR: {exc}")
        result = "FAILED"
    duration = int(time.time() - start)
    save_result_db(test_name, result, device_id, short_id, duration, "\n".join(logs))
    rotate_log_file()
    return result


def run_test_suite(short_id, test_names, device_id=None, log_callback=None):
    return {name: run_test(short_id, name, device_id, log_callback) for name in test_names}


def get_test_stats():
    return get_stats_db()


def get_recent_results(limit=100):
    return get_results_db(limit)


def get_test_categories():
    return TEST_CATEGORIES


init_db()
