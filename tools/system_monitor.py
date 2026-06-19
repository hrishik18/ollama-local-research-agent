"""System resource monitor — RAM, CPU, disk, and thermals.

Runs as a background daemon thread, logs samples every N seconds, and aborts the
agent process if thresholds are exceeded (critical thermal or OOM imminent).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

import psutil

log = logging.getLogger(__name__)


def read_linux_thermal() -> dict[str, float]:
    """Read /sys/class/thermal/thermal_zone*/temp on Linux. Returns deg C per zone."""
    out: dict[str, float] = {}
    base = Path("/sys/class/thermal")
    if not base.exists():
        return out
    for zone_dir in base.glob("thermal_zone*"):
        try:
            temp_path = zone_dir / "temp"
            type_path = zone_dir / "type"
            if not temp_path.exists():
                continue
            millideg = int(temp_path.read_text().strip())
            ztype = type_path.read_text().strip() if type_path.exists() else zone_dir.name
            out[f"{zone_dir.name}:{ztype}"] = millideg / 1000.0
        except Exception:
            continue
    return out


class SystemMonitor:
    """Background sampler. Aborts process if critical thresholds are crossed."""

    def __init__(
        self,
        log_path: str = "outputs/system_metrics.jsonl",
        sample_interval: float = 30.0,
        ram_abort_pct: float = 95.0,
        thermal_abort_c: float = 95.0,
        on_abort=None,  # optional callable(reason: str)
    ) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.sample_interval = sample_interval
        self.ram_abort_pct = ram_abort_pct
        self.thermal_abort_c = thermal_abort_c
        self.on_abort = on_abort

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._proc = psutil.Process(os.getpid())
        self._latest: dict[str, Any] = {}

    def sample(self) -> dict[str, Any]:
        vm = psutil.virtual_memory()
        thermal = read_linux_thermal()
        max_temp = max(thermal.values()) if thermal else None
        s = {
            "ts": time.time(),
            "cpu_pct": psutil.cpu_percent(interval=None),
            "ram_used_mb": vm.used / (1024 * 1024),
            "ram_total_mb": vm.total / (1024 * 1024),
            "ram_pct": vm.percent,
            "proc_rss_mb": self._proc.memory_info().rss / (1024 * 1024),
            "thermal_c": thermal,
            "max_temp_c": max_temp,
        }
        try:
            disk = psutil.disk_usage(str(Path.cwd()))
            s["disk_used_pct"] = disk.percent
        except Exception:
            pass
        self._latest = s
        return s

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                s = self.sample()
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(s) + "\n")

                # Abort conditions
                if s["ram_pct"] >= self.ram_abort_pct:
                    self._trigger_abort(f"RAM critical: {s['ram_pct']:.1f}% used")
                if s.get("max_temp_c") and s["max_temp_c"] >= self.thermal_abort_c:
                    self._trigger_abort(
                        f"Thermal critical: {s['max_temp_c']:.1f}C"
                    )
            except Exception as e:
                log.warning("Monitor sample failed: %s", e)
            self._stop.wait(self.sample_interval)

    def _trigger_abort(self, reason: str) -> None:
        log.error("[SystemMonitor] ABORT: %s", reason)
        if self.on_abort:
            try:
                self.on_abort(reason)
            except Exception:
                pass
        # Set stop so we don't fire repeatedly
        self._stop.set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="sys-monitor")
        self._thread.start()
        log.info("SystemMonitor started (interval=%.0fs).", self.sample_interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def latest(self) -> dict[str, Any]:
        return dict(self._latest)
