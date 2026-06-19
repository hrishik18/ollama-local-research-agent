"""Arxiv paper search via the official arxiv Python client."""

from __future__ import annotations

import logging
from typing import Any

import arxiv

log = logging.getLogger(__name__)


class ArxivSearchTool:
    name = "arxiv_search"
    description = "Search Arxiv for academic papers. Returns title, abstract, authors, PDF URL."

    def __init__(self, max_results: int = 20, sort_by: str = "relevance") -> None:
        self.max_results = max_results
        self.sort_criterion = (
            arxiv.SortCriterion.Relevance
            if sort_by == "relevance"
            else arxiv.SortCriterion.LastUpdatedDate
        )
        self._client = arxiv.Client(page_size=50, delay_seconds=3, num_retries=3)

    def run(self, query: str, max_results: int | None = None) -> list[dict[str, Any]]:
        n = max_results or self.max_results
        try:
            search = arxiv.Search(
                query=query,
                max_results=n,
                sort_by=self.sort_criterion,
            )
            results = []
            for r in self._client.results(search):
                results.append(
                    {
                        "arxiv_id": r.entry_id.split("/")[-1],
                        "title": r.title,
                        "abstract": r.summary,
                        "authors": [a.name for a in r.authors],
                        "published": r.published.isoformat() if r.published else None,
                        "pdf_url": r.pdf_url,
                        "categories": r.categories,
                    }
                )
            return results
        except Exception as e:
            log.warning("Arxiv search failed for %r: %s", query, e)
            return []
