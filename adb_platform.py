"""Linux-only ADB discovery and execution helpers."""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional, Tuple


def platform_name() -> str:
    """Return the supported platform name."""
    return "Linux"


def find_adb() -> Optional[str]:
    """Find and validate the native Linux ADB executable."""
    configured = os.environ.get("ADB_PATH", "").strip()
    candidates = []
    if configured:
        candidates.append(configured)
    candidates.extend(["/usr/bin/adb", "/usr/local/bin/adb"])
    found = shutil.which("adb")
    if found:
        candidates.append(found)

    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen or not os.path.isfile(candidate):
            continue
        seen.add(candidate)
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
    """Build a native Linux ADB command."""
    adb = find_adb()
    return [adb, *args] if adb else None


def ensure_network_device(device: Optional[str]) -> Tuple[bool, str]:
    """Connect to an ADB-over-TCP DUT using Linux ADB."""
    if not device:
        return True, ""
    command = adb_command("connect", device)
    if not command:
        return False, "Linux ADB executable is not available"
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
        low = output.lower()
        success = result.returncode == 0 and (
            "connected to" in low or "already connected" in low or "failed to authenticate" not in low
        )
        return success, output
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)


def get_adb_info() -> dict:
    """Return Linux ADB availability and version information."""
    adb = find_adb()
    if not adb:
        return {
            "available": False,
            "path": None,
            "platform": "Linux",
            "error": "No working Linux ADB client found",
        }
    try:
        result = subprocess.run(
            [adb, "version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        output = result.stdout or ""
        return {
            "available": result.returncode == 0,
            "path": adb,
            "platform": "Linux",
            "version": output.splitlines()[0] if output else "",
            "error": None if result.returncode == 0 else output.strip(),
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "available": False,
            "path": adb,
            "platform": "Linux",
            "error": str(exc),
        }
