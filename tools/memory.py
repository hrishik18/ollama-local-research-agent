"""FAISS-backed long-term memory using Ollama embeddings."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Optional

import faiss
import numpy as np

log = logging.getLogger(__name__)


class MemoryTool:
    name = "memory"
    description = "Long-term memory: store text chunks and retrieve relevant ones for a query."

    def __init__(
        self,
        llm,
        index_path: str = "state/faiss.index",
        metadata_path: str = "state/metadata.json",
        embedding_dim: int = 768,
        top_k_default: int = 6,
    ) -> None:
        self.llm = llm
        self.index_path = Path(index_path)
        self.metadata_path = Path(metadata_path)
        self.embedding_dim = embedding_dim
        self.top_k_default = top_k_default
        self._lock = threading.Lock()

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
            return len(self.metadata) - 1

    def add_batch(self, texts: list[str], metas: Optional[list[dict[str, Any]]] = None) -> list[int]:
        metas = metas or [{}] * len(texts)
        return [self.add(t, m) for t, m in zip(texts, metas)]

    def search(self, query: str, top_k: Optional[int] = None) -> list[dict[str, Any]]:
        k = top_k or self.top_k_default
        if self.index.ntotal == 0:
            return []
        emb = self.llm.embed(query)
        if not emb:
            return []
        vec = self._normalize(np.array([emb], dtype="float32"))
        scores, idxs = self.index.search(vec, min(k, self.index.ntotal))
        results = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx < 0 or idx >= len(self.metadata):
                continue
            entry = self.metadata[idx]
            results.append(
                {
                    "score": float(score),
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
