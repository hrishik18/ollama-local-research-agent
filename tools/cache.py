"""Disk-backed response cache for LLM calls and tool outputs.

Speeds up iteration loops: identical prompts return cached responses instantly,
which matters a lot when Qwen on CPU is slow.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)


class DiskCache:
    """Simple JSON-on-disk cache. Thread-safe. Keyed by SHA256 of canonical input."""

    def __init__(self, cache_dir: str = "cache", ttl_seconds: Optional[int] = None) -> None:
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _key(payload: Any) -> str:
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.dir / f"{key[:2]}" / f"{key}.json"

    def get(self, payload: Any) -> Optional[Any]:
        key = self._key(payload)
        path = self._path(key)
        if not path.exists():
            self.misses += 1
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                entry = json.load(f)
            if self.ttl_seconds is not None:
                age = time.time() - entry.get("ts", 0)
                if age > self.ttl_seconds:
                    self.misses += 1
                    return None
            self.hits += 1
            return entry.get("value")
        except Exception as e:
            log.warning("Cache read failed: %s", e)
            self.misses += 1
            return None

    def set(self, payload: Any, value: Any) -> None:
        key = self._key(payload)
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": time.time(), "value": value}
        with self._lock:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(entry, f, ensure_ascii=False)
            except Exception as e:
                log.warning("Cache write failed: %s", e)

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": (self.hits / total) if total else 0.0,
        }
