"""Wikipedia search and fetch."""

from __future__ import annotations

import logging
from typing import Any

import wikipediaapi

log = logging.getLogger(__name__)


class WikipediaTool:
    name = "wikipedia"
    description = "Fetch a Wikipedia article summary and section list by topic name."

    def __init__(self, lang: str = "en", max_chars: int = 4000) -> None:
        self.client = wikipediaapi.Wikipedia(
            language=lang,
            user_agent="ollama-local-research-agent/0.1 (educational use)",
        )
        self.max_chars = max_chars

    def run(self, title: str) -> dict[str, Any]:
        try:
            page = self.client.page(title)
            if not page.exists():
                return {"title": title, "error": "page not found", "summary": ""}
            return {
                "title": page.title,
                "url": page.fullurl,
                "summary": page.summary[: self.max_chars],
                "sections": [s.title for s in page.sections][:30],
            }
        except Exception as e:
            log.warning("Wikipedia fetch failed for %s: %s", title, e)
            return {"title": title, "error": str(e), "summary": ""}
