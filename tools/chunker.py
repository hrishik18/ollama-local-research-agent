"""Smarter, low-RAM text chunker.

Strategy:
1. Split into paragraphs (double newline)
2. Within long paragraphs, split into sentences (regex; no NLTK)
3. Greedy-pack into chunks up to `chunk_size` words, with `overlap` words carried over
4. Preserve sentence boundaries where possible

This produces semantically cleaner chunks than naive sliding-window word splits.
"""

from __future__ import annotations

import re
from typing import List

_SENT_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z\(\[])")


def split_sentences(text: str) -> List[str]:
    parts = _SENT_BOUNDARY.split(text)
    return [p.strip() for p in parts if p.strip()]


def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
    min_chunk_size: int = 80,
) -> List[str]:
    """Return semantically reasonable chunks (word-counted)."""
    if not text or not text.strip():
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    buf_words: List[str] = []

    def flush() -> None:
        nonlocal buf_words
        if buf_words and len(buf_words) >= min_chunk_size:
            chunks.append(" ".join(buf_words))
        elif buf_words and chunks:
            # Too small — merge into previous chunk
            chunks[-1] = chunks[-1] + " " + " ".join(buf_words)
        elif buf_words:
            chunks.append(" ".join(buf_words))
        buf_words = []

    for para in paragraphs:
        words = para.split()
        # Big paragraph — break by sentences
        if len(words) > chunk_size:
            sentences = split_sentences(para)
            # If the paragraph has no real sentence boundaries (e.g. all "word word word"),
            # treat each word-block as its own sentence so we still get reasonable chunks.
            if len(sentences) <= 1:
                # Hard-split by word window
                sentences = [
                    " ".join(words[i : i + chunk_size])
                    for i in range(0, len(words), chunk_size)
                ]
            for sent in sentences:
                sw = sent.split()
                # Sentence itself larger than chunk_size — hard-split it
                if len(sw) > chunk_size:
                    for j in range(0, len(sw), chunk_size):
                        sub = sw[j : j + chunk_size]
                        if len(buf_words) + len(sub) > chunk_size:
                            flush()
                            if overlap > 0 and chunks:
                                tail = chunks[-1].split()[-overlap:]
                                buf_words = list(tail)
                        buf_words.extend(sub)
                    continue
                if len(buf_words) + len(sw) > chunk_size:
                    flush()
                    if overlap > 0 and chunks:
                        tail = chunks[-1].split()[-overlap:]
                        buf_words = list(tail)
                buf_words.extend(sw)
        else:
            if len(buf_words) + len(words) > chunk_size:
                flush()
                if overlap > 0 and chunks:
                    tail = chunks[-1].split()[-overlap:]
                    buf_words = list(tail)
            buf_words.extend(words)

    flush()
    return chunks
