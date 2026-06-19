"""Fetch a web page and extract clean text content."""

from __future__ import annotations

import logging
from typing import Any

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (X11; Linux x86_64) ollama-research-agent/0.1"


class WebFetchTool:
    name = "web_fetch"
    description = "Download a web page and extract readable text (stripping nav/script)."

    def __init__(self, max_chars: int = 20000, timeout: int = 30) -> None:
        self.max_chars = max_chars
        self.timeout = timeout

    def run(self, url: str) -> dict[str, Any]:
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=self.timeout)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")

            # Strip non-content
            for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript"]):
                tag.decompose()

            title = (soup.title.string.strip() if soup.title and soup.title.string else "")
            text = soup.get_text(separator="\n", strip=True)
            # Collapse blank lines
            lines = [ln for ln in (l.strip() for l in text.splitlines()) if ln]
            cleaned = "\n".join(lines)[: self.max_chars]

            return {"url": url, "title": title, "text": cleaned, "n_chars": len(cleaned)}
        except Exception as e:
            log.warning("Web fetch failed for %s: %s", url, e)
            return {"url": url, "error": str(e), "text": ""}
