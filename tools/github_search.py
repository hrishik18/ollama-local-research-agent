"""GitHub repo / code search via the unauthenticated public API (rate-limited)."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

log = logging.getLogger(__name__)


class GithubSearchTool:
    name = "github_search"
    description = (
        "Search GitHub for repositories matching a query. Returns name, description, "
        "stars, language, topics, and URL. Uses GITHUB_TOKEN env var if set for higher "
        "rate limits."
    )

    def __init__(self, max_results: int = 10, rate_limit_seconds: float = 2.0) -> None:
        self.max_results = max_results
        self.rate_limit_seconds = rate_limit_seconds
        self._last_call = 0.0
        token = os.environ.get("GITHUB_TOKEN")
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "ollama-research-agent/0.1",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_call
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        self._last_call = time.time()

    def run(
        self,
        query: str,
        max_results: int | None = None,
        sort: str = "stars",
    ) -> list[dict[str, Any]]:
        self._rate_limit()
        n = max_results or self.max_results
        try:
            r = requests.get(
                "https://api.github.com/search/repositories",
                params={"q": query, "sort": sort, "per_page": n},
                headers=self.headers,
                timeout=30,
            )
            r.raise_for_status()
            items = r.json().get("items", [])
            return [
                {
                    "full_name": it["full_name"],
                    "url": it["html_url"],
                    "description": it.get("description") or "",
                    "stars": it.get("stargazers_count", 0),
                    "forks": it.get("forks_count", 0),
                    "language": it.get("language"),
                    "topics": it.get("topics", []),
                    "updated_at": it.get("updated_at"),
                    "archived": it.get("archived", False),
                }
                for it in items
            ]
        except Exception as e:
            log.warning("GitHub search failed for %r: %s", query, e)
            return []
