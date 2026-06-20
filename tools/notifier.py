"""Multi-channel run-finished notifier.

Notifies you when an overnight run completes (or fails). Channels in priority order:
1. ntfy.sh   — HTTP POST, no signup, push notifications to your phone/desktop.
                Just subscribe to your topic in the ntfy app.
2. notify-send — Linux desktop notification (if `notify-send` is on PATH).
3. console   — always-on fallback that prints to stderr.

Configure in config.yaml:

    notifications:
      enabled: true
      ntfy_topic: "my-secret-topic-name"     # https://ntfy.sh/<topic>
      ntfy_server: "https://ntfy.sh"         # or self-hosted
      desktop: true                           # try notify-send on Linux
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Any

import requests

log = logging.getLogger(__name__)


def notify(title: str, message: str, config: dict[str, Any] | None = None,
           priority: str = "default") -> list[str]:
    """Send a notification through every enabled channel. Returns channels used.

    `priority` follows ntfy semantics: min | low | default | high | urgent.
    """
    config = (config or {}).get("notifications", {}) if config else {}
    if not config.get("enabled", False):
        # Console fallback still fires so the user sees something
        log.info("[notify] %s — %s", title, message[:200])
        return ["console"]

    used: list[str] = []

    topic = config.get("ntfy_topic")
    if topic:
        try:
            server = config.get("ntfy_server", "https://ntfy.sh").rstrip("/")
            r = requests.post(
                f"{server}/{topic}",
                data=message.encode("utf-8"),
                headers={"Title": title, "Priority": priority, "Tags": "robot"},
                timeout=15,
            )
            r.raise_for_status()
            used.append("ntfy")
        except Exception as e:
            log.warning("ntfy notification failed: %s", e)

    if config.get("desktop", False) and shutil.which("notify-send"):
        try:
            subprocess.run(
                ["notify-send", "--app-name=ollama-agent", title, message[:500]],
                timeout=5, check=False,
            )
            used.append("notify-send")
        except Exception as e:
            log.warning("notify-send failed: %s", e)

    log.info("[notify] %s — %s (channels: %s)", title, message[:200], used or ["console"])
    return used or ["console"]
