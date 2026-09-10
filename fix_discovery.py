#!/usr/bin/env python3
"""Fix YTS discovery hanging on the MQTT connection and make parsing robust."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "yts_automation.py"

OLD_START = "def discover_yts_devices():\n"
OLD_END = "\n\ndef check_node():\n"

NEW_FUNCTION = r'''def discover_yts_devices():
    """
    Run `yts discover` without waiting indefinitely for its MQTT client.

    YTS prints the discovered devices and then may keep the process alive while
    trying to resolve mqtt://localhost:1883. The web UI only needs the device
    discovery lines, so collect output for a bounded period and terminate the
    CLI after discovery has had time to complete.
    """
    command = _yts_command("discover")
    env = os.environ.copy()
    adb = find_adb()
    if adb:
        env["PATH"] = f"{Path(adb).parent}:{env.get('PATH', '')}"
        env["ADB_PATH"] = adb

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        start_new_session=True,
    )

    def _as_text(value):
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    output = ""
    try:
        try:
            output, _ = process.communicate(timeout=20)
            output = _as_text(output)
        except subprocess.TimeoutExpired as exc:
            # Discovery output is already available even when the YTS process
            # remains alive because of its MQTT connection.
            output = _as_text(exc.stdout)
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                try:
                    process.terminate()
                except OSError:
                    pass
            try:
                tail, _ = process.communicate(timeout=5)
                output += _as_text(tail)
            except subprocess.TimeoutExpired as exc2:
                output += _as_text(exc2.stdout)
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    try:
                        process.kill()
                    except OSError:
                        pass
                tail, _ = process.communicate()
                output += _as_text(tail)
            logger.info("YTS discover timed out after 20s; using discovered device output")
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass

    mapping = {}
    for line in output.splitlines():
        # Normal YTS output, for example:
        # (90) unknown TV GSI on ARM SERIAL (adb: 192.168.2.31:5555)
        match = re.search(r"\(([^()\s]+)\).*?\(adb:\s*([^\s)]+)\)", line, re.IGNORECASE)
        if match:
            short_id, serial = match.group(1), match.group(2)
            mapping[serial] = short_id

    return mapping
'''


def main():
    source = TARGET.read_text(encoding="utf-8")
    start = source.find(OLD_START)
    if start < 0:
        raise RuntimeError("Could not find discover_yts_devices()")
    end = source.find(OLD_END, start)
    if end < 0:
        raise RuntimeError("Could not find end of discover_yts_devices()")
    updated = source[:start] + NEW_FUNCTION + source[end:]
    TARGET.write_text(updated, encoding="utf-8")
    print("Updated discover_yts_devices(): bounded YTS discovery, bytes-safe output, and robust Short ID parsing.")


if __name__ == "__main__":
    main()
