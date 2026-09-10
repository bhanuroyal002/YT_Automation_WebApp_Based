"""Cross-platform ADB discovery and execution helpers.

The application uses the native ADB client of the environment it is running in:
- Windows: adb.exe from PATH (or ADB_PATH)
- Linux/WSL: Linux adb from PATH (or ADB_PATH)

For WSL, a network-connected DUT can be supplied through ADB_DEVICE, e.g.
ADB_DEVICE=192.168.1.7:5555. This avoids depending on Windows executable
interop or the Windows ADB server.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Optional, Tuple


def _is_wsl() -> bool:
    if os.environ.get("WSL_INTEROP"):
        return True
    try:
        return "microsoft" in platform.release().lower() or "microsoft" in platform.version().lower()
    except Exception:
        return False


def platform_name() -> str:
    if os.name == "nt":
        return "Windows"
    if _is_wsl():
        return "WSL"
    return "Linux"


def _candidate_adb_paths() -> list[str]:
    candidates: list[str] = []
    configured = os.environ.get("ADB_PATH", "").strip()
    if configured:
        candidates.append(configured)

    found = shutil.which("adb")
    if found:
        candidates.append(found)

    if os.name == "nt":
        candidates.extend([
            os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
            os.path.expandvars(r"%ANDROID_HOME%\platform-tools\adb.exe"),
            os.path.expandvars(r"%ANDROID_SDK_ROOT%\platform-tools\adb.exe"),
        ])
    elif _is_wsl():
        # Only use a Linux adb in WSL. Windows .exe files are intentionally not
        # selected because WSL executable interop may be disabled.
        candidates.extend([
            "/usr/bin/adb",
            "/usr/local/bin/adb",
        ])
    else:
        candidates.extend(["/usr/bin/adb", "/usr/local/bin/adb"])

    unique: list[str] = []
    for path in candidates:
        if path and path not in unique and os.path.isfile(path):
            unique.append(path)
    return unique


def find_adb() -> Optional[str]:
    for candidate in _candidate_adb_paths():
        try:
            result = subprocess.run(
                [candidate, "version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
            if result.returncode == 0 and "Android Debug Bridge" in result.stdout:
                return candidate
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def adb_command(*args: str) -> Optional[list[str]]:
    adb = find_adb()
    if not adb:
        return None
    return [adb, *args]


def ensure_network_device(device: Optional[str]) -> Tuple[bool, str]:
    """Ensure a network ADB device is connected when ADB_DEVICE is configured."""
    if not device:
        return True, ""
    command = adb_command("connect", device)
    if not command:
        return False, "ADB executable is not available"
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        output = (result.stdout or "").strip()
        # adb connect returns success text such as "already connected" or
        # "connected to ...". Even when already connected, return success.
        success = result.returncode == 0 and (
            "connected to" in output.lower()
            or "already connected" in output.lower()
            or "failed to authenticate" not in output.lower()
        )
        return success, output
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)


def get_adb_info() -> dict:
    adb = find_adb()
    if not adb:
        return {
            "available": False,
            "path": None,
            "platform": platform_name(),
            "is_wsl": _is_wsl(),
            "error": "No working native ADB client found",
        }

    command = [adb, "version"]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        return {
            "available": result.returncode == 0,
            "path": adb,
            "platform": platform_name(),
            "is_wsl": _is_wsl(),
            "version": (result.stdout or "").splitlines()[0] if result.stdout else "",
            "error": None if result.returncode == 0 else (result.stdout or "ADB version check failed").strip(),
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "available": False,
            "path": adb,
            "platform": platform_name(),
            "is_wsl": _is_wsl(),
            "error": str(exc),
        }
