"""RSS / Atom feed reader. Uses stdlib + feedparser if available, falls back to bs4."""

from __future__ import annotations

import logging
from typing import Any

import requests

log = logging.getLogger(__name__)


class RssTool:
    name = "rss"
    description = "Fetch and parse an RSS or Atom feed. Returns recent entries."

    def __init__(self, max_entries: int = 15, timeout: int = 20) -> None:
        self.max_entries = max_entries
        self.timeout = timeout

    def run(self, url: str, max_entries: int | None = None) -> list[dict[str, Any]]:
        n = max_entries or self.max_entries
        try:
            import feedparser  # optional dep
            feed = feedparser.parse(url)
            entries = feed.entries[:n]
            return [
                {
                    "title": getattr(e, "title", ""),
                    "url": getattr(e, "link", ""),
                    "summary": (getattr(e, "summary", "") or "")[:1000],
                    "published": getattr(e, "published", ""),
                    "author": getattr(e, "author", None),
                }
                for e in entries
            ]
        except ImportError:
            # Fall back to bs4 raw parse
            try:
                from bs4 import BeautifulSoup
                r = requests.get(url, timeout=self.timeout)
                r.raise_for_status()
                soup = BeautifulSoup(r.content, "xml")
                items = soup.find_all(["item", "entry"])[:n]
                out = []
                for it in items:
                    title = it.find("title")
                    link = it.find("link")
                    summary = it.find(["description", "summary"])
                    pub = it.find(["pubDate", "published", "updated"])
                    out.append(
                        {
                            "title": title.get_text(strip=True) if title else "",
                            "url": (link.get_text(strip=True) if link and link.string else
                                    (link.get("href", "") if link else "")),
                            "summary": (summary.get_text(strip=True) if summary else "")[:1000],
                            "published": pub.get_text(strip=True) if pub else "",
                        }
                    )
                return out
            except Exception as e:
                log.warning("RSS fallback parse failed for %s: %s", url, e)
                return []
        except Exception as e:
            log.warning("RSS fetch failed for %s: %s", url, e)
            return []
