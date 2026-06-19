"""Local LLM interface via Ollama.

Wraps the local Qwen model (and embedding model) running through Ollama.
Designed for a 4GB-RAM Linux laptop: streaming, retry, JSON mode, low overhead.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Generator, Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised when the LLM call fails after retries."""


class LLM:
    def __init__(
        self,
        model: str = "qwen2.5:1.5b",
        embed_model: str = "nomic-embed-text",
        host: str = "http://localhost:11434",
        timeout: int = 300,
        default_temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> None:
        self.model = model
        self.embed_model = embed_model
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.default_temperature = default_temperature
        self.max_tokens = max_tokens

    # ---------- generation ----------

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        temperature: Optional[float] = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature if temperature is not None else self.default_temperature,
                "num_predict": self.max_tokens,
            },
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"

        try:
            r = requests.post(
                f"{self.host}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
            return data.get("response", "").strip()
        except requests.RequestException as e:
            log.warning("LLM call failed: %s", e)
            raise LLMError(str(e)) from e

    def generate_json(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> dict[str, Any]:
        """Generate and parse JSON. Retries with stricter prompt on parse failure."""
        raw = self.generate(prompt, system=system, json_mode=True, temperature=temperature)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.warning("JSON parse failed, retrying with strict instruction.")
            retry_prompt = (
                prompt
                + "\n\nIMPORTANT: Return ONLY valid JSON, no prose, no markdown fences."
            )
            raw = self.generate(retry_prompt, system=system, json_mode=True, temperature=0.0)
            try:
                return json.loads(raw)
            except json.JSONDecodeError as e:
                raise LLMError(f"Could not parse JSON: {raw[:300]}") from e

    def generate_stream(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Generator[str, None, None]:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": temperature if temperature is not None else self.default_temperature,
                "num_predict": self.max_tokens,
            },
        }
        if system:
            payload["system"] = system

        with requests.post(
            f"{self.host}/api/generate",
            json=payload,
            timeout=self.timeout,
            stream=True,
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    if "response" in chunk:
                        yield chunk["response"]
                    if chunk.get("done"):
                        break
                except json.JSONDecodeError:
                    continue

    # ---------- embeddings ----------

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def embed(self, text: str) -> list[float]:
        """Get embedding for a single text."""
        r = requests.post(
            f"{self.host}/api/embeddings",
            json={"model": self.embed_model, "prompt": text},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json().get("embedding", [])

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts (sequential — Ollama is single-threaded per request)."""
        return [self.embed(t) for t in texts]

    # ---------- health ----------

    def health_check(self) -> bool:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=5)
            r.raise_for_status()
            tags = r.json().get("models", [])
            names = [m.get("name", "") for m in tags]
            return any(self.model in n for n in names)
        except requests.RequestException:
            return False
