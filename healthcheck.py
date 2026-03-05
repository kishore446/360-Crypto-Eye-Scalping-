#!/usr/bin/env python3
"""Healthcheck — verifies the 360 Crypto Eye bot process is running."""
import os
import sys


def _bot_process_running() -> bool:
    """Return True if a process running main.py is found in /proc."""
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/cmdline", "rb") as fh:
                    cmdline = fh.read().replace(b"\x00", b" ").decode("utf-8", errors="replace")
                if "python" in cmdline and "main.py" in cmdline:
                    return True
            except (FileNotFoundError, PermissionError):
                continue
    except FileNotFoundError:
        pass
    return False


if not _bot_process_running():
    print("Bot process (main.py) not found.", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
