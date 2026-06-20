"""Prompt compression via headroom-ai (https://github.com/chopratejas/headroom).

Why this exists for *us*:
- Qwen 1.5B on a 4 GB CPU laptop is slow. Wall-time is dominated by prompt
  tokens (each one is a forward pass before the first output token streams).
- Cutting input tokens 50-90% on tool-output-heavy turns (search results,
  PDF chunks, agent_log digests) directly shortens every step — and helps
  the laptop avoid the thermal_abort threshold during overnight runs.
- Headroom is local-first, reversible, and library-mode requires no proxy.

Design choices for this repo:
- Lazy import. If `headroom-ai` is not installed, we silently no-op so the
  agent still works on a bare 4 GB box.
- Skip compression when `json_mode=True` — strict JSON output is fragile and
  the JSON-formatted prompts here are already short.
- Skip when the input is below `min_input_chars` (default 2000). For short
  prompts the headroom call costs more than it saves.
- Log every compression to a JSONL so the dashboard can show savings.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Lazy-imported on first use; None means "not installed, run as no-op".
_HEADROOM = None
_HEADROOM_TRIED = False


def _load_headroom():
    global _HEADROOM, _HEADROOM_TRIED
    if _HEADROOM_TRIED:
        return _HEADROOM
    _HEADROOM_TRIED = True
    try:
        from headroom import compress  # type: ignore
        _HEADROOM = compress
        log.info("headroom-ai loaded; prompt compression enabled")
    except Exception as e:  # ImportError or any init error
        log.info("headroom-ai not available (%s); compressor will no-op", e)
        _HEADROOM = None
    return _HEADROOM


class PromptCompressor:
    """Wrap headroom.compress() with safe fallbacks and per-call logging.

    Public API:
        compressor.compress(system, prompt, json_mode=False) -> (system, prompt)
        compressor.stats() -> aggregate dict
    """

    def __init__(
        self,
        enabled: bool = True,
        min_input_chars: int = 2000,
        model_hint: str = "gpt-4o",  # headroom uses this for tokenizer selection
        log_path: Optional[str] = None,
    ) -> None:
        self.enabled = enabled
        self.min_input_chars = min_input_chars
        self.model_hint = model_hint
        self.log_path = Path(log_path) if log_path else None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

        self._calls = 0
        self._skipped = 0
        self._tokens_before = 0
        self._tokens_after = 0
        self._failures = 0

    # ---------- public ----------

    def compress(
        self,
        system: Optional[str],
        prompt: str,
        json_mode: bool = False,
    ) -> tuple[Optional[str], str]:
        """Return (system, prompt) — possibly compressed. Never raises."""
        if not self.enabled:
            return system, prompt
        if json_mode:
            # Compression can reorder/reshape content; JSON output is too brittle.
            self._skipped += 1
            return system, prompt

        total = len(prompt) + (len(system) if system else 0)
        if total < self.min_input_chars:
            self._skipped += 1
            return system, prompt

        fn = _load_headroom()
        if fn is None:
            self._skipped += 1
            return system, prompt

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        t0 = time.time()
        try:
            result = fn(messages, model=self.model_hint)
        except Exception as e:
            self._failures += 1
            log.warning("headroom compress failed (%s); using original prompt", e)
            return system, prompt
        latency_ms = int((time.time() - t0) * 1000)

        # Pull messages back out. headroom returns either an object with
        # `.messages` / `.tokens_before` / `.tokens_after` or a dict — handle both.
        msgs = getattr(result, "messages", None)
        if msgs is None and isinstance(result, dict):
            msgs = result.get("messages")
        tokens_before = (
            getattr(result, "tokens_before", None)
            if hasattr(result, "tokens_before")
            else (result.get("tokens_before") if isinstance(result, dict) else None)
        )
        tokens_after = (
            getattr(result, "tokens_after", None)
            if hasattr(result, "tokens_after")
            else (result.get("tokens_after") if isinstance(result, dict) else None)
        )

        if not msgs:
            self._failures += 1
            return system, prompt

        new_system, new_prompt = system, prompt
        for m in msgs:
            role = m.get("role")
            content = m.get("content")
            if not isinstance(content, str):
                continue
            if role == "system":
                new_system = content
            elif role == "user":
                new_prompt = content

        self._calls += 1
        if isinstance(tokens_before, int):
            self._tokens_before += tokens_before
        if isinstance(tokens_after, int):
            self._tokens_after += tokens_after

        if self.log_path:
            try:
                with self.log_path.open("a", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            {
                                "ts": time.time(),
                                "tokens_before": tokens_before,
                                "tokens_after": tokens_after,
                                "chars_before": total,
                                "chars_after": len(new_prompt) + (len(new_system) if new_system else 0),
                                "latency_ms": latency_ms,
                                "model_hint": self.model_hint,
                            }
                        )
                        + "\n"
                    )
            except Exception:
                pass  # logging must never break the agent

        return new_system, new_prompt

    def stats(self) -> dict:
        saved = self._tokens_before - self._tokens_after
        ratio = (saved / self._tokens_before) if self._tokens_before else 0.0
        return {
            "calls": self._calls,
            "skipped": self._skipped,
            "failures": self._failures,
            "tokens_before": self._tokens_before,
            "tokens_after": self._tokens_after,
            "tokens_saved": saved,
            "compression_ratio": round(ratio, 4),
        }


def build_from_config(config: dict, default_log_path: str) -> Optional[PromptCompressor]:
    """Build a PromptCompressor from the top-level config dict, or None if disabled."""
    cfg = (config or {}).get("compression") or {}
    if not cfg.get("enabled", False):
        return None
    return PromptCompressor(
        enabled=True,
        min_input_chars=int(cfg.get("min_input_chars", 2000)),
        model_hint=cfg.get("model_hint", "gpt-4o"),
        log_path=cfg.get("log_path", default_log_path),
    )
