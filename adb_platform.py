"""Cross-platform ADB discovery and execution helpers."""
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

    if os.name == "nt":
        candidates.extend([
            os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
            os.path.expandvars(r"%ANDROID_HOME%\platform-tools\adb.exe"),
            os.path.expandvars(r"%ANDROID_SDK_ROOT%\platform-tools\adb.exe"),
        ])
    else:
        # Prefer known native Linux paths before PATH. This avoids a broken
        # /usr/local/bin/adb wrapper shadowing /usr/bin/adb under WSL.
        candidates.extend(["/usr/bin/adb", "/usr/local/bin/adb"])

    found = shutil.which("adb")
    if found:
        candidates.append(found)

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
    return [adb, *args] if adb else None


def ensure_network_device(device: Optional[str]) -> Tuple[bool, str]:
    if not device:
        return True, ""
    command = adb_command("connect", device)
    if not command:
        return False, "ADB executable is not available"
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", timeout=15, check=False)
        output = (result.stdout or "").strip()
        low = output.lower()
        success = result.returncode == 0 and (
            "connected to" in low or "already connected" in low or "failed to authenticate" not in low
        )
        return success, output
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)


def get_adb_info() -> dict:
    adb = find_adb()
    if not adb:
        return {"available": False, "path": None, "platform": platform_name(),
                "is_wsl": _is_wsl(), "error": "No working native ADB client found"}
    try:
        result = subprocess.run([adb, "version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", timeout=10, check=False)
        output = result.stdout or ""
        return {"available": result.returncode == 0, "path": adb, "platform": platform_name(),
                "is_wsl": _is_wsl(), "version": output.splitlines()[0] if output else "",
                "error": None if result.returncode == 0 else output.strip()}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "path": adb, "platform": platform_name(),
                "is_wsl": _is_wsl(), "error": str(exc)}
