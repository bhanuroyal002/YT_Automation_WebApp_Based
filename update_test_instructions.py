#!/usr/bin/env python3
"""Apply certification test instructions to yts_automation.py."""
from pathlib import Path
import json
import pprint
import re

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "test_instructions.json"
TARGET = ROOT / "yts_automation.py"


def main():
    instructions = json.loads(SOURCE.read_text(encoding="utf-8"))
    source = TARGET.read_text(encoding="utf-8")
    pattern = re.compile(
        r"# Keep the instructions keyed to every test\..*?"
        r"(?=\n# ============================================\n# Runtime YTS lifecycle)",
        re.S,
    )
    replacement = (
        "# Detailed test instructions sourced from the certification instruction table.\n"
        "TEST_INSTRUCTIONS = "
        + pprint.pformat(instructions, width=100, sort_dicts=False)
        + "\n\n"
    )
    updated, count = pattern.subn(replacement, source, count=1)
    if count != 1:
        raise RuntimeError("Could not locate the TEST_INSTRUCTIONS block in yts_automation.py")
    updated = updated.replace("--test-version=20250415", "--test-version=20250721")
    TARGET.write_text(updated, encoding="utf-8")
    print(f"Updated {len(instructions)} test instructions and aligned test-version to 20250721.")


if __name__ == "__main__":
    main()
