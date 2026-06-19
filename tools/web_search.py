"""DuckDuckGo web search — no API key required."""

from __future__ import annotations

import logging
import time
from typing import Any

from duckduckgo_search import DDGS

log = logging.getLogger(__name__)


class WebSearchTool:
    name = "web_search"
    description = "Search the web for general information. Returns titles, snippets, and URLs."

    def __init__(self, max_results: int = 8, rate_limit_seconds: float = 3.0) -> None:
        self.max_results = max_results
        self.rate_limit_seconds = rate_limit_seconds
        self._last_call = 0.0

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_call
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        self._last_call = time.time()

    def run(self, query: str, max_results: int | None = None) -> list[dict[str, Any]]:
        self._rate_limit()
        n = max_results or self.max_results
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=n))
            return [
                {
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", ""),
                }
                for r in results
            ]
        except Exception as e:
            log.warning("Web search failed for %r: %s", query, e)
            return []
