"""PDF download + text extraction + chunking using PyMuPDF (low-memory)."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import fitz  # pymupdf
import requests

log = logging.getLogger(__name__)


class PdfReaderTool:
    name = "pdf_reader"
    description = "Download a PDF from URL, extract text, return chunked sections."

    def __init__(
        self,
        download_dir: str = "state/pdfs",
        max_pages: int = 50,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> None:
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.max_pages = max_pages
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def _download(self, url: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()[:16]
        path = self.download_dir / f"{h}.pdf"
        if path.exists():
            return path
        log.info("Downloading PDF: %s", url)
        r = requests.get(url, timeout=120, stream=True)
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return path

    def _extract_text(self, path: Path) -> str:
        text_parts: list[str] = []
        doc = fitz.open(path)
        try:
            n_pages = min(len(doc), self.max_pages)
            for i in range(n_pages):
                text_parts.append(doc[i].get_text("text"))
        finally:
            doc.close()
        return "\n".join(text_parts)

    def _chunk(self, text: str) -> list[str]:
        # Use the shared semantic chunker
        from .chunker import chunk_text
        return chunk_text(text, chunk_size=self.chunk_size, overlap=self.chunk_overlap)

    def run(self, url: str) -> dict[str, Any]:
        try:
            path = self._download(url)
            text = self._extract_text(path)
            chunks = self._chunk(text)
            return {
                "url": url,
                "local_path": str(path),
                "n_chars": len(text),
                "n_chunks": len(chunks),
                "chunks": chunks,
            }
        except Exception as e:
            log.warning("PDF read failed for %s: %s", url, e)
            return {"url": url, "error": str(e), "chunks": []}
