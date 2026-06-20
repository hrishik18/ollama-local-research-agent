"""Hacker News search via Algolia API (no key required)."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

log = logging.getLogger(__name__)

BASE = "https://hn.algolia.com/api/v1"


class HackerNewsTool:
    name = "hacker_news"
    description = (
        "Search Hacker News (via Algolia). Returns top stories with title, url, points, "
        "comments count, and snippet."
    )

    def __init__(self, max_results: int = 10, rate_limit_seconds: float = 1.0) -> None:
        self.max_results = max_results
        self.rate_limit_seconds = rate_limit_seconds
        self._last_call = 0.0

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_call
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        self._last_call = time.time()

    def run(
        self,
        query: str,
        max_results: int | None = None,
        tags: str = "story",
        sort_by: str = "relevance",  # or "date"
    ) -> list[dict[str, Any]]:
        self._rate_limit()
        n = max_results or self.max_results
        endpoint = "search" if sort_by == "relevance" else "search_by_date"
        try:
            r = requests.get(
                f"{BASE}/{endpoint}",
                params={"query": query, "tags": tags, "hitsPerPage": n},
                timeout=20,
            )
            r.raise_for_status()
            hits = r.json().get("hits", [])
            return [
                {
                    "title": h.get("title") or h.get("story_title") or "",
                    "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                    "points": h.get("points", 0),
                    "num_comments": h.get("num_comments", 0),
                    "author": h.get("author"),
                    "created_at": h.get("created_at"),
                    "snippet": (h.get("story_text") or "")[:300],
                }
                for h in hits
            ]
        except Exception as e:
            log.warning("HN search failed for %r: %s", query, e)
            return []
