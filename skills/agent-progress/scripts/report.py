#!/usr/bin/env python3
"""Forward an explicit report to the panel installed on this computer."""
import os
from pathlib import Path
import subprocess
import sys


def main():
    data = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "omarchy-agent-progress"
    helper = data / "progress.py"
    if not helper.is_file() or not (data / "install.json").is_file():
        print("Agent Progress is not installed on this computer. Use the panel's connected computer.", file=sys.stderr)
        return 1
    raw = sys.stdin.buffer.read(8193)
    if len(raw) > 8192:
        print("Agent Progress report exceeds 8 KiB.", file=sys.stderr)
        return 1
    try:
        result = subprocess.run([sys.executable, str(helper), "observe"], input=raw, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        print("Agent Progress reporter unavailable.", file=sys.stderr)
        return 1
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
