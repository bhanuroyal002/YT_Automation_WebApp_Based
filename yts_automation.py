#!/usr/bin/env python3
"""
YTS Automation Script - Optimized for Web Integration
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
import urllib.error
import atexit
import signal
import sqlite3
import threading
import logging
from contextlib import contextmanager
from pathlib import Path

from adb_platform import adb_command, ensure_network_device, find_adb, get_adb_info

# ============================================
# Constants and Configuration
# ============================================

# Cache settings
CACHE_TIMEOUT = 60  # Cache device details for 60 seconds
MAX_RETRIES = 2  # Maximum retries for failed tests
TEST_TIMEOUT = 300  # Timeout for tests in seconds
MAX_LOG_SIZE_MB = 10  # Maximum log file size before rotation

# Device cache
_device_cache = {}
_cache_timestamps = {}

# YTS is downloaded at application startup into a private temporary directory.
# Nothing from the YTS package is shipped with this repository.
YTS_DOWNLOAD_URL = os.environ.get(
    "YTS_DOWNLOAD_URL",
    "http://yts.devicecertification.youtube/yts_server.zip",
)
YTS_DOWNLOAD_TIMEOUT = int(os.environ.get("YTS_DOWNLOAD_TIMEOUT", "120"))
_yts_runtime_dir = None
_yts_script_path = None
_yts_prepare_lock = threading.Lock()
_yts_processes = set()
_yts_processes_lock = threading.Lock()

# ============================================
# Database Setup
# ============================================
# Runtime data lives outside the repository root.
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
    """Get database connection with context manager."""
    conn = sqlite3.connect(str(DATABASE_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Initialize the database tables."""
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS test_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_name TEXT NOT NULL,
                device_id TEXT,
                short_id TEXT,
                status TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                duration INTEGER,
                logs TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS test_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_name TEXT UNIQUE,
                total_runs INTEGER DEFAULT 0,
                passes INTEGER DEFAULT 0,
                failures INTEGER DEFAULT 0,
                avg_duration REAL DEFAULT 0
            )
        ''')
        conn.commit()

def save_result_db(test_name, status, device_id=None, short_id=None, duration=None, logs=None):
    """Save test result to database."""
    try:
        with get_db() as conn:
            # Insert test result - 6 placeholders, 6 parameters
            conn.execute('''
                INSERT INTO test_results (test_name, device_id, short_id, status, duration, logs)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (test_name, device_id, short_id, status, duration, logs))
            conn.commit()
            
            # Update metrics
            cursor = conn.execute('SELECT total_runs, passes, failures, avg_duration FROM test_metrics WHERE test_name = ?', (test_name,))
            existing = cursor.fetchone()
            
            if existing:
                total = existing['total_runs'] + 1
                passes = existing['passes'] + (1 if status == 'PASSED' else 0)
                failures = existing['failures'] + (1 if status == 'FAILED' else 0)
                avg_duration = ((existing['avg_duration'] * existing['total_runs']) + (duration or 0)) / total if total > 0 else 0
                
                conn.execute('''
                    UPDATE test_metrics 
                    SET total_runs = ?, passes = ?, failures = ?, avg_duration = ?
                    WHERE test_name = ?
                ''', (total, passes, failures, avg_duration, test_name))
            else:
                conn.execute('''
                    INSERT INTO test_metrics (test_name, total_runs, passes, failures, avg_duration)
                    VALUES (?, 1, ?, ?, ?)
                ''', (test_name, 
                      1 if status == 'PASSED' else 0, 
                      1 if status == 'FAILED' else 0, 
                      duration or 0))
            
            conn.commit()
    except Exception:
        logger.exception("Failed to save result for test %s", test_name)

def get_results_db(limit=100):
    """Get recent test results from database."""
    with get_db() as conn:
        cursor = conn.execute('''
            SELECT * FROM test_results 
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (limit,))
        return [dict(row) for row in cursor.fetchall()]

def get_stats_db():
    """Get test statistics from database."""
    with get_db() as conn:
        cursor = conn.execute('''
            SELECT 
                test_name,
                total_runs,
                passes,
                failures,
                ROUND(avg_duration, 2) as avg_duration,
                ROUND(passes * 100.0 / total_runs, 1) as pass_rate
            FROM test_metrics
            ORDER BY total_runs DESC
        ''')
        return [dict(row) for row in cursor.fetchall()]

def rotate_log_file(log_file=None, max_size_mb=10):
    """Rotate the application log when it exceeds the configured size."""
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
# Test Configuration
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
    "LiveDRM", "In-app HDR HLG", "In-app HDR PQ", 
    "In-app Visual Audio / Video Sync", "DRM Purchased Movie",
    "Multi-App Performance", "System Overlay", 
    "YouTube Music Endurance", "Live streaming",
}

YTS_TEST_WAIT_SECONDS = {
    "LiveDRM": 18 * 60,
    "In-app HDR HLG": 5 * 60,
    "In-app HDR PQ": 5 * 60,
    "YouTube Music Endurance": 5 * 60 + 10,
    "Live streaming": 12 * 60 * 60,
}

# Test categories for UI grouping
TEST_CATEGORIES = {
    "Media Tests": ["Adaptive Bit Rate", "Adaptive Bit Rate - DRM", "Resizing"],
    "Aspect Ratio Tests": ["21:9 Aspect Ratio", "4:3 Aspect Ratio", "16:9 Aspect Ratio", "17:30 Aspect Ratio"],
    "ETC Tests": ["Fonts", "Captions", "Localization", "TTS", "Screensaver", "High Contrast Text Setting", 
                   "TTS Setting", "Animated WebP", "Non-animated WebP", "Page Visibility Overlay", "Language Setting"],
    "Manual Tests": ["LiveDRM", "YouTube Music Endurance", "Live streaming"],
    "Performance Tests": ["Multi-App Performance", "System Overlay"],
    "HDR Tests": ["In-app HDR HLG", "In-app HDR PQ"],
    "Launch Tests": ["In-app Visual Audio / Video Sync", "DRM Purchased Movie", "Sign-in Persistence"],
    "Guided Tests": ["Params Remote", "System-wide Exit Key", "Alternate Time Zone", "Params Menu"],
    "Endurance Tests": ["12 Hour Endurance", "Persistence Cookie 200 times"],
    "Voice Tests": ["[Voice&Search] Soft-mic Button"],
    "Time Tests": ["Current Time"]
}

# ============================================
# Test Instructions
# ============================================

TEST_INSTRUCTIONS = {
    "LiveDRM": """Verify the launched video has a LIVE badge and enable Stats for Nerds. Observe playback for 18 minutes.

Pass/Fail Criteria:
- 'Live Latency' and 'Live Mode' fields must appear in Stats for Nerds
- 'Protected' must include WVA (Widevine DRM)
- Dropped frames ≤ 0.5% of total frames
- No green/magenta corrupted frames
- Few to no skipping, stuttering, buffering, pausing""",

    "12 Hour Endurance": """Run the test and let it run for 12 hours.

Pass/Fail Criteria:
- Device must continuously play for 12 hours without stopping
- No crashes or interruptions""",

    "YouTube Music Endurance": """Enable screensaver: adb shell settings put secure screensaver_enabled 1
Allow audio-only playback to continue past screensaver timeout.

Pass/Fail Criteria:
- Screensaver must NOT activate
- Device must not enter sleep mode""",

    "Persistence Cookie 200 times": """Run the test and wait for completion.

Pass/Fail Criteria:
- Console and screen must show PASSED after completion""",

    "Live streaming": """Run: yts launch {shortId} "stick=0"
Then run the channel deeplink: yts launch {shortId} "https://www.youtube.com/tv?c=UC4R8DWoMoI7CAwX8_LjQHig"
Select and play any LIVE video.

Pass/Fail Criteria:
- Playback starts quickly (similar to regular videos)
- Pause for 10s → Resume works normally
- Minimal rebuffering or bitrate switching
- Must sustain 10 minutes (device should support 12+ hours)""",

    "Adaptive Bit Rate": """Follow on-screen instructions.

Pass/Fail Criteria:
- Starts at low resolution → adapts upward
- Smooth transition
- No stutter, skip, or pause
- May pass even if it doesn't reach the maximum resolution""",

    "Adaptive Bit Rate - DRM": """Observe the Stream Info panel for 90–120 seconds.

Pass/Fail Criteria:
- Start at low → adapt to higher resolution
- Smooth transitions
- No stutter/skipping/pausing""",

    "21:9 Aspect Ratio": """Follow on-screen instructions.

Pass/Fail Criteria:
- Top & bottom letterbox present
- No cropping
- Disney castle flag and "PICTURES" text visible""",

    "4:3 Aspect Ratio": """Follow on-screen instructions.

Pass/Fail Criteria:
- Left/right letterbox borders present
- Video must not be cropped""",

    "16:9 Aspect Ratio": """Follow on-screen instructions.

Pass/Fail Criteria:
- Border visible
- Circles must remain round
- Should fill all pixels on most devices""",

    "17:30 Aspect Ratio": """Follow on-screen instructions.

Pass/Fail Criteria:
- Tall rectangle with blank left/right
- No cropping; vertical bars must match""",

    "[Voice&Search] Soft-mic Button": """Launch YouTube, navigate to Search.
Confirm mic icon shows next to keyboard.
Focus → Press OK.
Say "Eric Clapton solo" (no remote button pressed).

Pass/Fail Criteria:
- UI indicates listening
- Search results or playback for that query appears""",

    "Current Time": """Run: yts launch {shortId} "stick=0"
Then run: yts launch {shortId} "https://www.youtube.com/tv?env_showUIStats=true&use_toa=true&v=RgodTgI2EDo"
Observe first 10 seconds, pause/resume and repeat with seeks as described.

Pass/Fail Criteria:
- Overlay time must be within 100 ms of paused video time at all test points""",

    "Params Remote": """Run guided test: "Params Remote"

Pass/Fail Criteria:
- Screen must show RESULT: PASSED""",

    "System-wide Exit Key": """Run guided test: "In-app System-wide Exit Key"

Pass/Fail Criteria:
- Screen must show RESULT: PASSED""",

    "Resizing": """Run guided test: "Media Resizing 2024+"

Pass/Fail Criteria:
- Must show RESULT: PASSED
- Video vs container resize lag must be < 100ms in captured video""",

    "Alternate Time Zone": """Run guided test: "Time Alternate Time Zones"

Pass/Fail Criteria:
- Guided test must end with RESULT: PASSED""",

    "TTS": """Pre-check: adb shell service check texttospeech
If not found → N/A
Run guided test: "Speech TTS"

Pass/Fail Criteria:
- Must display PASSED""",

    "Required If Unreserved": """Run guided test: "Key Event Required If Unreserved 2024+"

Pass/Fail Criteria:
- Must display PASSED
- Reserved keys must be skipped""",

    "Localization": """Run guided test: "ETC Localization"

Pass/Fail Criteria:
- Must display PASSED""",

    "Screensaver": """Run guided test: "ETC Page Visibility Screensaver"

Pass/Fail Criteria:
- Must display PASSED""",

    "High Contrast Text Setting": """Run guided test: "ETC High Contrast Text"

Pass/Fail Criteria:
- Must display PASSED""",

    "TTS Setting": """Run guided test: "ETC TTS"

Pass/Fail Criteria:
- Must display PASSED""",

    "Animated WebP": """Run guided test: "ETC Animated WebP"

Pass/Fail Criteria:
- Must display PASSED""",

    "Non-animated WebP": """Run guided test: "ETC Non-animated WebP"

Pass/Fail Criteria:
- Must display PASSED""",

    "Fonts": """Run guided test: "ETC Fonts"

Pass/Fail Criteria:
- Must display RESULT: PASSED
- All fonts render correctly without issues""",

    "Page Visibility Overlay": """Run guided test: "ETC Page Visibility Overlay"

Pass/Fail Criteria:
- Must display PASSED""",

    "Language Setting": """Run guided test: "ETC Language"

Pass/Fail Criteria:
- Must display PASSED""",

    "Captions": """If closed captions unsupported → mark N/A
Run guided test: "ETC Captions"

Pass/Fail Criteria:
- Must display PASSED""",

    "Params Menu": """Run guided test: "Params Menu"

Pass/Fail Criteria:
- Must display PASSED""",

    "In-app HDR HLG": """Run yts launch with HDR HLG video.

Pass/Fail Criteria:
- Codecs include HDR type: vp09.02 or av01.0.##M.10
- Color eotf: arib-std-b67 (HLG)
- Colorspace: bt2020
- Display switches to HDR mode""",

    "In-app HDR PQ": """Run yts launch with HDR PQ video.

Pass/Fail Criteria:
- Codecs show HDR
- eotf = smpte2084 (PQ)
- Colorspace = bt2020
- Display switches to HDR mode""",

    "In-app Visual Audio / Video Sync": """Run the playlist and enable Stats for Nerds.
Perform pause/seek checks per test.

Pass/Fail Criteria:
- Current fps = Optimal fps
- No perceived A/V desync after pause/seek actions""",

    "DRM Purchased Movie": """Run yts launch and purchase the test asset if required.

Pass/Fail Criteria:
- Stats show WVA in protected/key system
- Optimal Resolution = device's maximum supported resolution""",

    "Multi-App Performance": """Run the certPerformanceRoutine as described.
Perform the app-switch flow.

Pass/Fail Criteria (both runs):
- Browse → Watch pct50 ≤ 1500ms
- Row→Row pct95 ≥ 30
- Tile→Tile pct95 ≥ 30
- Input latency pct95 < 200ms""",

    "System Overlay": """Run certPerformanceRoutine.
Open a system overlay during the second run.

Pass/Fail Criteria:
- No performance degradation when overlay open
- Same performance metrics as Multi-App Performance test""",

    "Sign-in Persistence": """Launch YouTube, sign in, unplug power 90s, plug back, relaunch and verify sign-in.

Pass/Fail Criteria:
- After power cycle, user stays signed in"""
}

# ============================================
# Core Functions
# ============================================

def _process_env():
    env = os.environ.copy()
    if _yts_runtime_dir:
        env["YTS_RUNFILES"] = str(_yts_runtime_dir / "package")

    # Put the verified native ADB directory first in PATH so YTS subprocesses
    # use the same ADB client as the web application. This is especially
    # important in WSL where a broken /usr/local/bin/adb wrapper may otherwise
    # shadow the working Linux adb binary.
    adb = find_adb()
    if adb:
        adb_dir = str(Path(adb).resolve().parent)
        path_parts = [p for p in env.get("PATH", "").split(os.pathsep) if p]
        path_parts = [p for p in path_parts if os.path.normcase(p) != os.path.normcase(adb_dir)]
        env["PATH"] = os.pathsep.join([adb_dir, *path_parts])
    return env

def _run_process(args, cwd=None, capture_output=True):
    """Run a process without a shell and return (stdout+stderr, returncode)."""
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            env=_process_env(),
            capture_output=capture_output,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        output = (result.stdout or "") + (result.stderr or "")
        return output.strip(), result.returncode
    except (OSError, ValueError) as exc:
        return str(exc), 1

def _safe_extract_zip(zip_path, destination):
    """Safely extract a YTS zip without allowing path traversal."""
    destination = Path(destination).resolve()
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if target != destination and destination not in target.parents:
                raise RuntimeError(f"Unsafe path in YTS archive: {member.filename}")
        archive.extractall(destination)


def _find_yts_script(root):
    """Find the YTS launcher inside an extracted yts_server package."""
    root = Path(root)
    candidates = []
    for name in ("yts", "yts.cmd", "yts.bat", "yts.exe"):
        candidates.extend(root.rglob(name))
    for candidate in candidates:
        if candidate.is_file() and candidate.parent.name == "yts_server":
            try:
                text = candidate.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                text = ""
            if "YTS_RUNFILES" in text or "YTS_BIN_LOADER" in text:
                return candidate
    return None


def prepare_yts():
    """Download and prepare a fresh YTS package for this application run."""
    global _yts_runtime_dir, _yts_script_path

    with _yts_prepare_lock:
        if _yts_script_path and _yts_script_path.exists():
            return _yts_script_path

        runtime_dir = Path(tempfile.mkdtemp(prefix="yts_automation_"))
        zip_path = runtime_dir / "yts_server.zip"
        extract_dir = runtime_dir / "package"

        logger.info("Downloading YTS CLI from %s", YTS_DOWNLOAD_URL)
        try:
            request = urllib.request.Request(
                YTS_DOWNLOAD_URL,
                headers={"User-Agent": "YTS-Automation-WebApp/1.0"},
            )
            with urllib.request.urlopen(request, timeout=YTS_DOWNLOAD_TIMEOUT) as response, zip_path.open("wb") as output:
                shutil.copyfileobj(response, output)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            shutil.rmtree(runtime_dir, ignore_errors=True)
            raise RuntimeError(f"Unable to download YTS package: {exc}") from exc

        if not zipfile.is_zipfile(zip_path):
            shutil.rmtree(runtime_dir, ignore_errors=True)
            raise RuntimeError("Downloaded YTS package is not a valid ZIP archive")

        try:
            extract_dir.mkdir(parents=True, exist_ok=True)
            _safe_extract_zip(zip_path, extract_dir)
            script = _find_yts_script(extract_dir)
        except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
            shutil.rmtree(runtime_dir, ignore_errors=True)
            raise RuntimeError(f"Unable to prepare downloaded YTS package: {exc}") from exc

        if not script:
            shutil.rmtree(runtime_dir, ignore_errors=True)
            raise RuntimeError("YTS launcher was not found in the downloaded package")

        if os.name != "nt":
            try:
                script.chmod(script.stat().st_mode | 0o111)
            except OSError as exc:
                shutil.rmtree(runtime_dir, ignore_errors=True)
                raise RuntimeError(f"Unable to make YTS executable: {exc}") from exc

        _yts_runtime_dir = runtime_dir
        _yts_script_path = script
        os.environ["YTS_RUNTIME_DIR"] = str(runtime_dir)
        logger.info("YTS prepared in temporary directory: %s", runtime_dir)
        return script


def cleanup_yts():
    """Terminate YTS children and remove the temporary YTS package."""
    global _yts_runtime_dir, _yts_script_path

    with _yts_processes_lock:
        processes = list(_yts_processes)
        _yts_processes.clear()

    for process in processes:
        try:
            _terminate_process_tree(process)
        except Exception:
            logger.exception("Failed to terminate YTS process %s", getattr(process, "pid", "unknown"))

    runtime_dir = _yts_runtime_dir
    _yts_runtime_dir = None
    _yts_script_path = None
    if runtime_dir:
        shutil.rmtree(runtime_dir, ignore_errors=True)
        logger.info("Removed temporary YTS directory: %s", runtime_dir)


def _yts_script():
    """Return the YTS launcher from this run's temporary download only."""
    return prepare_yts()


# Always clean the per-run YTS download when the Python process exits.
atexit.register(cleanup_yts)

def _adb_command(*args):
    """Return the native ADB command for the current OS.

    Windows uses adb.exe; WSL/Linux uses the Linux adb client.  We never
    execute a Windows .exe from WSL, because WSL executable interop may be
    disabled.
    """
    return adb_command(*args)

def _yts_command(*args):
    """Return a YTS command that works on Linux/WSL and native Windows.

    Linux/WSL executes the downloaded Node shebang launcher directly. Native
    Windows executes that same launcher through node.exe and supplies
    YTS_RUNFILES so the unpacked package is resolved as a local YTS tree.
    """
    script = _yts_script()
    if os.name == "nt":
        node = shutil.which("node")
        if not node:
            return None
        return [node, str(script), *args]
    return [str(script), *args]

def _build_yts_args(short_id, test_name):
    """Build argv from a known command template."""
    import shlex

    template = YTS_TEST_COMMANDS.get(test_name)
    if not template:
        return None
    
    formatted = template.format(shortId=short_id)
    
    # Convert the known template into argv without shell parsing.
    # posix=True removes quoting characters while preserving quoted arguments as one item.
    args = shlex.split(formatted, posix=True)
    
    # Remove the first element if it's 'yts'
    if args and args[0] == 'yts':
        return args[1:]
    
    return args

def check_node():
    """Check if Node.js is installed."""
    return shutil.which("node") is not None

def check_yts_cli():
    """Check if YTS CLI is available."""
    command = _yts_command("--version")
    if not command:
        return False
    _, code = _run_process(command)
    return code == 0

def check_adb_devices():
    """Get list of ADB devices using the native client for this OS."""
    configured_device = os.environ.get("ADB_DEVICE", "").strip()
    if configured_device:
        ok, message = ensure_network_device(configured_device)
        if not ok:
            logger.warning("Unable to connect configured ADB_DEVICE %s: %s", configured_device, message)
    command = _adb_command("devices")
    if not command:
        return []

    out, code = _run_process(command)
    if code != 0:
        return []

    devices = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices

def discover_yts_devices():
    """Discover YTS devices and get short IDs."""
    configured_device = os.environ.get("ADB_DEVICE", "").strip()
    if configured_device:
        ok, message = ensure_network_device(configured_device)
        if not ok:
            logger.warning("Unable to connect configured ADB_DEVICE %s: %s", configured_device, message)
    command = _yts_command("discover")
    if not command:
        return {}

    out, code = _run_process(command)
    if code != 0:
        return {}

    shortid_map = {}
    for line in out.splitlines():
        shortid_match = re.search(r"\(([^)]+)\)", line)
        adb_match = re.search(r"adb:\s*([^\s)]+)", line)
        if shortid_match and adb_match:
            shortid_map[adb_match.group(1).strip()] = shortid_match.group(1).strip()
    return shortid_map

def get_device_details(device_id):
    """Get detailed device information."""
    details = {
        "fingerprint": "Unknown",
        "security_patch": "Unknown",
        "android_version": "Unknown",
        "product": "Unknown",
        "model": "Unknown",
        "manufacturer": "Unknown",
    }

    command = _adb_command("-s", device_id, "shell", "getprop")
    if not command:
        return details

    props, code = _run_process(command)
    if code != 0:
        return details

    property_map = {
        "ro.build.fingerprint": "fingerprint",
        "ro.build.version.security_patch": "security_patch",
        "ro.build.version.release": "android_version",
        "ro.product.name": "product",
        "ro.product.model": "model",
        "ro.product.manufacturer": "manufacturer",
    }

    for line in props.splitlines():
        match = re.match(r"\[([^\]]+)\]:\s*\[([^\]]*)\]", line)
        if match and match.group(1) in property_map:
            details[property_map[match.group(1)]] = match.group(2)

    return details

def get_device_details_cached(device_id):
    """Get device details with caching."""
    current_time = time.time()
    
    if device_id in _device_cache and device_id in _cache_timestamps:
        if current_time - _cache_timestamps[device_id] < CACHE_TIMEOUT:
            return _device_cache[device_id]
    
    details = get_device_details(device_id)
    _device_cache[device_id] = details
    _cache_timestamps[device_id] = current_time
    return details

def log_result(test_name, status):
    """Append a compact result entry to the application log."""
    rotate_log_file(LOG_PATH, MAX_LOG_SIZE_MB)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            timestamp = datetime.datetime.now().isoformat(timespec="seconds")
            f.write(f"{timestamp} - {test_name}: {status}\n")
    except OSError:
        logger.exception("Failed to write result log")

# ============================================
# Test Execution Functions
# ============================================

def _terminate_process_tree(process):
    """Terminate a process and its children."""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            os.killpg(process.pid, signal.SIGTERM)
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        try: process.kill()
        except OSError: pass


def _start_process(command):
    kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "text": True, "encoding": "utf-8", "errors": "replace", "bufsize": 1, "env": _process_env()}
    if os.name == "nt": kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else: kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    with _yts_processes_lock:
        _yts_processes.add(process)
    return process


def _stream_process(command, log_callback):
    process = _start_process(command)
    output, seen_lines = [], set()
    if process.stdout:
        for line in process.stdout:
            line = line.rstrip()
            if line and line not in seen_lines:
                seen_lines.add(line); output.append(line)
                if log_callback: log_callback(line)
    return process.wait(), output


def _detect_result(lines):
    """Detect PASSED/FAILED from output lines."""
    text = "\n".join(lines)
    if re.search(r"\b(RESULT:\s*PASSED|✓\s*PASSED)\b", text, re.I):
        return "PASSED"
    if re.search(r"\b(RESULT:\s*FAILED|✗\s*FAILED)\b", text, re.I):
        return "FAILED"
    return None

def run_automated_test(test_name, command, log_callback, timeout=TEST_TIMEOUT):
    """Run an automated test with a real process-level timeout."""
    try:
        if log_callback: log_callback("Running automated test...")
        start = time.monotonic(); process = _start_process(command)
        output, seen_lines = [], set()
        def reader():
            if not process.stdout: return
            for line in process.stdout:
                line = line.rstrip()
                if line and line not in seen_lines:
                    seen_lines.add(line); output.append(line)
                    if log_callback: log_callback(line)
        thread = threading.Thread(target=reader, daemon=True); thread.start(); thread.join(timeout)
        if thread.is_alive():
            _terminate_process_tree(process); thread.join(5); result = "TIMEOUT"
            if log_callback: log_callback(f"⚠️ Test timed out after {timeout} seconds")
        else:
            process.wait(timeout=5); detected = _detect_result(output)
            result = detected if detected else ("PASSED" if process.returncode == 0 else "FAILED")
        duration = int(time.monotonic() - start); log_result(test_name, result)
        if log_callback: log_callback(f"Test completed with result: {result} (duration: {duration}s)")
        return result
    except (OSError, subprocess.SubprocessError) as exc:
        if log_callback: log_callback(f"ERROR running test: {exc}")
        return "FAILED"


def run_manual_test(test_name, command, log_callback):
    """Run a manual test for its configured observation window."""
    try:
        if log_callback: log_callback("Running manual test - follow the on-screen instructions.")
        start = time.monotonic(); timeout = YTS_TEST_WAIT_SECONDS.get(test_name, TEST_TIMEOUT); process = _start_process(command)
        output, seen_lines = [], set()
        def reader():
            if not process.stdout: return
            for line in process.stdout:
                line = line.rstrip()
                if line and line not in seen_lines:
                    seen_lines.add(line); output.append(line)
                    if log_callback: log_callback(line)
        thread = threading.Thread(target=reader, daemon=True); thread.start(); thread.join(timeout)
        detected = _detect_result(output)
        if detected:
            _terminate_process_tree(process); result = detected
        elif thread.is_alive():
            _terminate_process_tree(process); thread.join(5); result = "MANUAL_REVIEW_REQUIRED"
        else:
            process.wait(timeout=5); result = _detect_result(output) or "MANUAL_REVIEW_REQUIRED"
        log_result(test_name, result)
        if log_callback: log_callback(f"Test observation finished: {result} (duration: {int(time.monotonic() - start)}s)")
        return result
    except (OSError, subprocess.SubprocessError) as exc:
        if log_callback: log_callback(f"ERROR running test: {exc}")
        return "FAILED"


def run_test(short_id, test_name, device=None, log_callback=None):
    """Run a single test with retry logic."""
    max_retries = 2 if test_name not in YTS_MANUAL_TESTS else 0
    
    for attempt in range(max_retries + 1):
        if attempt > 0:
            if log_callback:
                log_callback(f"🔄 Retry attempt {attempt}/{max_retries}")
            time.sleep(3)
        
        if log_callback:
            log_callback(f"Starting test: {test_name}")

        args = _build_yts_args(short_id, test_name)
        if not args:
            if log_callback:
                log_callback(f"ERROR: No command found for test {test_name}")
            save_result_db(test_name, "FAILED", device_id=device, short_id=short_id)
            return "FAILED"

        command = _yts_command(*args)
        if not command:
            if log_callback:
                log_callback("ERROR: Runtime YTS CLI is not available")
            save_result_db(test_name, "FAILED", device_id=device, short_id=short_id)
            return "FAILED"

        if log_callback:
            log_callback(f"Command: {' '.join(command)}")
            log_callback(f"Manual test: {test_name in YTS_MANUAL_TESTS}")

        start_time = time.time()
        
        if test_name in YTS_MANUAL_TESTS:
            result = run_manual_test(test_name, command, log_callback)
        else:
            result = run_automated_test(test_name, command, log_callback)
        
        duration = int(time.time() - start_time)
        
        # Save result to database
        save_result_db(test_name, result, device_id=device, short_id=short_id, duration=duration)
        
        # If passed or manual test, return immediately
        if result == "PASSED" or test_name in YTS_MANUAL_TESTS:
            return result
        elif attempt == max_retries:
            return result
    
    return "FAILED"

def run_test_suite(short_id, test_names, device=None, log_callback=None):
    """Run a suite of tests and generate summary report."""
    results = {}
    passed = 0
    failed = 0
    timed_out = 0
    total = len(test_names)
    suite_start_time = time.time()
    
    for idx, test_name in enumerate(test_names, 1):
        if log_callback:
            log_callback(f"\n{'='*50}")
            log_callback(f"📋 [{idx}/{total}] Running: {test_name}")
            log_callback(f"{'='*50}")
        
        result = run_test(short_id, test_name, device, log_callback)
        results[test_name] = result
        
        if result == "PASSED":
            passed += 1
        elif result == "TIMEOUT":
            timed_out += 1
        else:
            failed += 1
        
        # Update progress in logs
        if log_callback:
            log_callback(f"📊 Progress: {idx}/{total} | ✅ {passed} | ❌ {failed} | ⏰ {timed_out}")
    
    # Calculate suite statistics
    suite_duration = int(time.time() - suite_start_time)
    pass_rate = round(passed * 100 / total, 1) if total > 0 else 0
    
    # Generate summary
    summary = f"""
{'='*50}
📊 TEST SUITE SUMMARY
{'='*50}
Total Tests: {total}
✅ Passed: {passed}
❌ Failed: {failed}
⏰ Timed Out: {timed_out}
📈 Pass Rate: {pass_rate}%
⏱️ Total Duration: {suite_duration}s
{'='*50}
"""
    
    if log_callback:
        log_callback(summary)
    
    # Save suite summary to database
    save_result_db("SUITE_SUMMARY", "COMPLETED", 
                   device_id=device, short_id=short_id,
                   duration=suite_duration,
                   logs=f"Total: {total}, Passed: {passed}, Failed: {failed}, Timed Out: {timed_out}, Pass Rate: {pass_rate}%")
    
    return results

def get_test_categories():
    """Get test categories for UI grouping."""
    return TEST_CATEGORIES

def get_test_stats():
    """Get test statistics."""
    return get_stats_db()

def get_recent_results(limit=100):
    """Get recent test results."""
    return get_results_db(limit)

# ============================================
# Initialize Database
# ============================================

init_db()