"""Desktop notifications for long-running tasks.

Uses platform-native commands: osascript on macOS, notify-send on Linux.
"""

from __future__ import annotations

import platform
import subprocess
import time
from typing import Any


def _system() -> str:
    return platform.system().lower()


def notify(
    title: str, message: str, *, sound: bool = False, subtitle: str = ""
) -> dict[str, object]:
    """Send a desktop notification.

    Parameters
    ----------
    title:
        Notification title (short).
    message:
        Notification body.
    sound:
        Play a sound (macOS only).
    subtitle:
        Optional subtitle (macOS only).
    """
    sysname = _system()
    try:
        if sysname == "darwin":
            script_parts = [f'display notification "{message}" with title "{title}"']
            if subtitle:
                script_parts.append(f'subtitle "{subtitle}"')
            if sound:
                script_parts.append("sound name \"default\"")
            subprocess.run(
                ["osascript", "-e", " ".join(script_parts)],
                capture_output=True, timeout=5,
            )
        elif sysname == "linux":
            cmd = ["notify-send", title, message]
            subprocess.run(cmd, capture_output=True, timeout=5)
        else:
            return {"ok": False, "error": "unsupported_platform", "platform": sysname}
    except FileNotFoundError:
        return {"ok": False, "error": "notify_command_not_found"}
    except Exception as exc:
        return {"ok": False, "error": "notify_failed", "detail": str(exc)}

    return {"ok": True, "platform": sysname, "title": title, "sent_at": time.time()}


def notify_if_long(
    title: str, elapsed_seconds: float, *, threshold: float = 30.0
) -> dict[str, object]:
    """Send a notification only if *elapsed_seconds* exceeds *threshold*."""
    if elapsed_seconds < threshold:
        return {"ok": True, "notified": False, "reason": "below_threshold"}
    minutes = elapsed_seconds / 60.0
    return notify(title, f"Completed in {minutes:.1f} min")
