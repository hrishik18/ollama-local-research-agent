"""Semantic Scholar paper search — no API key required (rate-limited public tier)."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

log = logging.getLogger(__name__)

BASE = "https://api.semanticscholar.org/graph/v1"


class SemanticScholarTool:
    name = "semantic_scholar"
    description = (
        "Search Semantic Scholar for papers. Returns title, abstract, year, citation count, "
        "tldr (1-sentence summary), and open-access PDF URL when available."
    )

    def __init__(self, max_results: int = 15, rate_limit_seconds: float = 3.0) -> None:
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
        fields = "title,abstract,year,citationCount,authors,tldr,openAccessPdf,externalIds"
        try:
            r = requests.get(
                f"{BASE}/paper/search",
                params={"query": query, "limit": n, "fields": fields},
                timeout=30,
            )
            r.raise_for_status()
            data = r.json().get("data", [])
            return [
                {
                    "paper_id": p.get("paperId"),
                    "title": p.get("title"),
                    "abstract": p.get("abstract") or "",
                    "year": p.get("year"),
                    "citation_count": p.get("citationCount", 0),
                    "tldr": (p.get("tldr") or {}).get("text") if p.get("tldr") else None,
                    "pdf_url": (p.get("openAccessPdf") or {}).get("url"),
                    "external_ids": p.get("externalIds", {}),
                    "authors": [a.get("name") for a in (p.get("authors") or [])[:5]],
                }
                for p in data
            ]
        except Exception as e:
            log.warning("Semantic Scholar search failed for %r: %s", query, e)
            return []
