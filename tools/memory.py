"""FAISS + BM25 hybrid memory using Ollama embeddings.

Hybrid retrieval combines:
- Dense vector similarity (FAISS / cosine)
- Sparse keyword match (BM25)

Final score = alpha * vector_score + (1-alpha) * bm25_score (both min-max normalized).
This dramatically improves recall on rare-term queries (acronyms, citations, IDs).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Optional

import faiss
import numpy as np
from rank_bm25 import BM25Okapi

log = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    return [t for t in text.lower().split() if len(t) > 1]


class MemoryTool:
    name = "memory"
    description = (
        "Hybrid long-term memory (FAISS vector + BM25 keyword). "
        "Store text chunks with metadata and retrieve relevant ones for a query."
    )

    def __init__(
        self,
        llm,
        index_path: str = "state/faiss.index",
        metadata_path: str = "state/metadata.json",
        embedding_dim: int = 768,
        top_k_default: int = 6,
        hybrid_alpha: float = 0.6,
    ) -> None:
        self.llm = llm
        self.index_path = Path(index_path)
        self.metadata_path = Path(metadata_path)
        self.embedding_dim = embedding_dim
        self.top_k_default = top_k_default
        self.hybrid_alpha = hybrid_alpha
        self._lock = threading.Lock()
        self._bm25: Optional[BM25Okapi] = None
        self._bm25_dirty = True

        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        if self.index_path.exists():
            self.index = faiss.read_index(str(self.index_path))
            log.info("Loaded FAISS index with %d vectors.", self.index.ntotal)
        else:
            self.index = faiss.IndexFlatIP(self.embedding_dim)

        if self.metadata_path.exists():
            with open(self.metadata_path, "r", encoding="utf-8") as f:
                self.metadata: list[dict[str, Any]] = json.load(f)
        else:
            self.metadata = []
        self._bm25_dirty = True

    def save(self) -> None:
        with self._lock:
            faiss.write_index(self.index, str(self.index_path))
            with open(self.metadata_path, "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, ensure_ascii=False)

    @staticmethod
    def _normalize(v: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(v, axis=1, keepdims=True)
        norm[norm == 0] = 1.0
        return v / norm

    def _rebuild_bm25(self) -> None:
        if not self.metadata:
            self._bm25 = None
            self._bm25_dirty = False
            return
        corpus = [_tokenize(m["text"]) for m in self.metadata]
        self._bm25 = BM25Okapi(corpus)
        self._bm25_dirty = False

    def add(self, text: str, meta: Optional[dict[str, Any]] = None) -> int:
        emb = self.llm.embed(text)
        if not emb:
            log.warning("Empty embedding, skipping.")
            return -1

        vec = np.array([emb], dtype="float32")
        if vec.shape[1] != self.embedding_dim:
            log.warning(
                "Embedding dim mismatch: %d vs configured %d. Rebuilding index.",
                vec.shape[1], self.embedding_dim,
            )
            self.embedding_dim = vec.shape[1]
            self.index = faiss.IndexFlatIP(self.embedding_dim)

        vec = self._normalize(vec)
        with self._lock:
            self.index.add(vec)
            entry = {"text": text, "meta": meta or {}}
            self.metadata.append(entry)
            self._bm25_dirty = True
            return len(self.metadata) - 1

    def add_batch(self, texts: list[str], metas: Optional[list[dict[str, Any]]] = None) -> list[int]:
        metas = metas or [{}] * len(texts)
        return [self.add(t, m) for t, m in zip(texts, metas)]

    @staticmethod
    def _minmax(arr: np.ndarray) -> np.ndarray:
        if arr.size == 0:
            return arr
        lo, hi = float(arr.min()), float(arr.max())
        if hi - lo < 1e-9:
            return np.zeros_like(arr)
        return (arr - lo) / (hi - lo)

    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        hybrid: bool = True,
    ) -> list[dict[str, Any]]:
        k = top_k or self.top_k_default
        if self.index.ntotal == 0 or not self.metadata:
            return []

        # Vector scores
        emb = self.llm.embed(query)
        if not emb:
            return []
        qvec = self._normalize(np.array([emb], dtype="float32"))
        # Get top-N candidates from vector for re-ranking (overfetch)
        n_candidates = min(max(k * 4, 20), self.index.ntotal)
        v_scores, v_idxs = self.index.search(qvec, n_candidates)
        v_scores = v_scores[0]
        v_idxs = v_idxs[0]

        if not hybrid:
            results = []
            for s, i in zip(v_scores, v_idxs):
                if 0 <= i < len(self.metadata):
                    e = self.metadata[i]
                    results.append({"score": float(s), "text": e["text"], "meta": e["meta"]})
            return results[:k]

        # BM25 scores over the same candidate set
        if self._bm25_dirty:
            self._rebuild_bm25()

        bm25_scores_full = (
            self._bm25.get_scores(_tokenize(query)) if self._bm25 else np.zeros(len(self.metadata))
        )

        # Restrict to valid candidates
        valid = [(s, i) for s, i in zip(v_scores, v_idxs) if 0 <= i < len(self.metadata)]
        if not valid:
            return []
        v_arr = np.array([s for s, _ in valid], dtype="float32")
        b_arr = np.array([bm25_scores_full[i] for _, i in valid], dtype="float32")

        v_norm = self._minmax(v_arr)
        b_norm = self._minmax(b_arr)
        combined = self.hybrid_alpha * v_norm + (1.0 - self.hybrid_alpha) * b_norm

        order = np.argsort(-combined)
        results = []
        for pos in order[:k]:
            idx = valid[pos][1]
            entry = self.metadata[idx]
            results.append(
                {
                    "score": float(combined[pos]),
                    "vec_score": float(v_arr[pos]),
                    "bm25_score": float(b_arr[pos]),
                    "text": entry["text"],
                    "meta": entry["meta"],
                }
            )
        return results

    def stats(self) -> dict[str, Any]:
        return {
            "n_vectors": self.index.ntotal,
            "dim": self.embedding_dim,
            "sources": len(set(m.get("meta", {}).get("source", "") for m in self.metadata)),
        }

