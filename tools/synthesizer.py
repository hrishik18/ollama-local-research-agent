"""Multi-paper / multi-chunk synthesis tool."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


SYNTH_SYSTEM = """You are an expert research synthesizer. Given a set of text excerpts
from multiple sources, produce a clear, structured synthesis. Always cite sources by
their [source_id] marker. Be concise and factual. If sources disagree, note it."""

SYNTH_PROMPT = """Topic / question: {topic}

Source excerpts:
{excerpts}

Write a synthesis that:
1. Identifies the key findings or claims across sources
2. Notes agreements and disagreements
3. Cites every claim with the [source_id] marker
4. Is well-organized with short paragraphs or bullet points
5. Ends with a 2-3 sentence summary

Synthesis:"""


class SynthesizerTool:
    name = "synthesizer"
    description = "Synthesize multiple memory chunks into a cohesive section on a topic."

    def __init__(self, llm, memory) -> None:
        self.llm = llm
        self.memory = memory

    def run(self, topic: str, top_k: int = 8, max_chars_per_chunk: int = 800) -> dict[str, Any]:
        chunks = self.memory.search(topic, top_k=top_k)
        if not chunks:
            return {"topic": topic, "synthesis": "", "sources_used": []}

        excerpts_parts = []
        sources_used = []
        for i, c in enumerate(chunks):
            sid = c["meta"].get("source", f"chunk_{i}")
            sources_used.append(sid)
            text = c["text"][:max_chars_per_chunk]
            excerpts_parts.append(f"[{sid}] {text}")
        excerpts = "\n\n".join(excerpts_parts)

        prompt = SYNTH_PROMPT.format(topic=topic, excerpts=excerpts)
        synthesis = self.llm.generate(prompt, system=SYNTH_SYSTEM, temperature=0.5)
        return {
            "topic": topic,
            "synthesis": synthesis,
            "sources_used": list(set(sources_used)),
            "n_chunks_used": len(chunks),
        }
