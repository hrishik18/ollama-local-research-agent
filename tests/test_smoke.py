"""Smoke tests that work without Ollama running.

Run with: pytest tests/ -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow imports from project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest


# --- Chunker ---

def test_chunker_short_text():
    from tools.chunker import chunk_text
    chunks = chunk_text("Hello world.", chunk_size=500, overlap=50)
    assert chunks == ["Hello world."]


def test_chunker_long_text_word_count():
    from tools.chunker import chunk_text
    # 1500 words, chunk_size=300
    text = " ".join(["word"] * 1500)
    chunks = chunk_text(text, chunk_size=300, overlap=30, min_chunk_size=10)
    assert len(chunks) >= 4
    # No chunk should hugely exceed 300 words
    for c in chunks:
        assert len(c.split()) <= 350


def test_chunker_preserves_paragraphs():
    from tools.chunker import chunk_text
    p1 = "First paragraph with a few words."
    p2 = "Second paragraph also with some words."
    chunks = chunk_text(p1 + "\n\n" + p2, chunk_size=500, overlap=0, min_chunk_size=1)
    joined = " ".join(chunks)
    assert "First paragraph" in joined
    assert "Second paragraph" in joined


# --- Disk cache ---

def test_cache_roundtrip(tmp_path):
    from tools.cache import DiskCache
    c = DiskCache(cache_dir=str(tmp_path / "cache"))
    assert c.get({"q": "hello"}) is None
    c.set({"q": "hello"}, {"answer": 42})
    assert c.get({"q": "hello"}) == {"answer": 42}
    stats = c.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1


def test_cache_different_keys(tmp_path):
    from tools.cache import DiskCache
    c = DiskCache(cache_dir=str(tmp_path / "cache"))
    c.set({"q": "a"}, 1)
    c.set({"q": "b"}, 2)
    assert c.get({"q": "a"}) == 1
    assert c.get({"q": "b"}) == 2


# --- Prompt.md parsing ---

def test_prompt_md_parse(tmp_path):
    from main import read_prompt_md, update_prompt_md
    pf = tmp_path / "prompt.md"
    pf.write_text(
        "## GOAL\n\nResearch X.\n\n---\n\n## LEARNINGS\n\nnone\n\n---\n\n"
        "## ITERATION\n\ncurrent_iteration: 3\nlast_run_ts: never\nlast_run_status: ok\n",
        encoding="utf-8",
    )
    goal, it = read_prompt_md(str(pf))
    assert "Research X" in goal
    assert it == 3

    update_prompt_md(str(pf), 4, "done", learnings_to_append="- Found 10 papers")
    new_text = pf.read_text(encoding="utf-8")
    assert "current_iteration: 4" in new_text
    assert "last_run_status: done" in new_text


# --- Skills loader ---

def test_skills_load():
    from tools.skills import _parse_skill, SkillRegistry
    skill = _parse_skill(ROOT / "skills" / "extract_paper_findings.md")
    assert skill is not None
    assert skill["name"] == "extract_paper_findings"
    assert "{source_id}" in skill["template"]
    assert "{text}" in skill["template"]


def test_skills_registry_loads_all():
    from tools.skills import SkillRegistry

    class FakeLLM:
        def generate(self, *a, **kw):
            return "ok"
        def generate_json(self, *a, **kw):
            return {}

    reg = SkillRegistry(FakeLLM(), skills_dir=str(ROOT / "skills"))
    assert "extract_paper_findings" in reg.skills
    assert "compare_approaches" in reg.skills
    assert "evaluate_progress" in reg.skills
    assert "improve_prompt" in reg.skills
    assert "summarize_chunks" in reg.skills


# --- System monitor (no abort path) ---

def test_system_monitor_sample(tmp_path):
    from tools.system_monitor import SystemMonitor
    m = SystemMonitor(log_path=str(tmp_path / "metrics.jsonl"), sample_interval=999)
    s = m.sample()
    assert "ram_pct" in s
    assert "cpu_pct" in s
    assert "proc_rss_mb" in s
    assert s["ram_total_mb"] > 0


# --- Config loads cleanly ---

def test_config_loads():
    import yaml
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    for key in ("llm", "agent", "tools", "paths", "monitor", "cache"):
        assert key in cfg, f"missing config section: {key}"
    assert "memory" in cfg["tools"]
    assert "hybrid_alpha" in cfg["tools"]["memory"]
