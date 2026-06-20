"""v0.5 tests: headroom-ai prompt compression integration.

These tests do NOT require headroom-ai to be installed. They verify:
1. PromptCompressor no-ops gracefully when headroom isn't available.
2. PromptCompressor skips JSON-mode and short prompts.
3. PromptCompressor uses an injected stub `compress` fn correctly.
4. LLM passes prompts through the compressor before building the payload.
5. Dashboard /api/compression endpoint reads the log JSONL.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.compressor import PromptCompressor, build_from_config  # noqa: E402
from llm import LLM  # noqa: E402


# ---------- PromptCompressor ----------

def test_disabled_is_noop():
    c = PromptCompressor(enabled=False)
    s, p = c.compress("sys", "x" * 5000)
    assert s == "sys"
    assert p == "x" * 5000
    assert c.stats()["calls"] == 0


def test_short_prompt_is_skipped():
    c = PromptCompressor(enabled=True, min_input_chars=2000)
    s, p = c.compress("sys", "short prompt")
    assert p == "short prompt"
    assert c.stats()["skipped"] == 1
    assert c.stats()["calls"] == 0


def test_json_mode_is_skipped():
    c = PromptCompressor(enabled=True, min_input_chars=10)
    s, p = c.compress("sys", "x" * 500, json_mode=True)
    assert p == "x" * 500
    assert c.stats()["skipped"] == 1


def test_missing_headroom_is_noop(monkeypatch):
    """If headroom isn't installed, compress() returns originals unchanged."""
    import tools.compressor as cm
    monkeypatch.setattr(cm, "_HEADROOM_TRIED", False)
    monkeypatch.setattr(cm, "_HEADROOM", None)

    # Force the lazy loader to "fail to find" headroom.
    monkeypatch.setattr(cm, "_load_headroom", lambda: None)

    c = PromptCompressor(enabled=True, min_input_chars=10)
    s, p = c.compress("sys", "x" * 500)
    assert p == "x" * 500
    assert c.stats()["skipped"] == 1


def test_stub_compress_called(tmp_path, monkeypatch):
    """When headroom is present, PromptCompressor uses its output."""
    log_path = tmp_path / "compression.jsonl"

    class _StubResult:
        def __init__(self, messages, tokens_before, tokens_after):
            self.messages = messages
            self.tokens_before = tokens_before
            self.tokens_after = tokens_after

    def fake_compress(messages, model=None):
        # Replace user content with a much shorter version.
        out = []
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": "COMPRESSED"})
            else:
                out.append(m)
        return _StubResult(out, tokens_before=1000, tokens_after=100)

    import tools.compressor as cm
    monkeypatch.setattr(cm, "_load_headroom", lambda: fake_compress)

    c = PromptCompressor(
        enabled=True, min_input_chars=10, log_path=str(log_path)
    )
    s, p = c.compress("sys", "x" * 500)
    assert p == "COMPRESSED"
    stats = c.stats()
    assert stats["calls"] == 1
    assert stats["tokens_before"] == 1000
    assert stats["tokens_after"] == 100
    assert stats["tokens_saved"] == 900
    assert log_path.exists()
    rec = json.loads(log_path.read_text().strip())
    assert rec["tokens_before"] == 1000


# ---------- build_from_config ----------

def test_build_from_config_disabled():
    assert build_from_config({}, "x.jsonl") is None
    assert build_from_config({"compression": {"enabled": False}}, "x.jsonl") is None


def test_build_from_config_enabled(tmp_path):
    cfg = {"compression": {"enabled": True, "min_input_chars": 50, "log_path": str(tmp_path / "c.jsonl")}}
    c = build_from_config(cfg, "default.jsonl")
    assert isinstance(c, PromptCompressor)
    assert c.min_input_chars == 50


# ---------- LLM integration ----------

def test_llm_passes_through_compressor(monkeypatch):
    """LLM.generate should hand (system, prompt) to compressor before HTTP."""
    seen = {}

    class _Stub:
        def compress(self, system, prompt, json_mode=False):
            seen["system"] = system
            seen["prompt"] = prompt
            seen["json_mode"] = json_mode
            return "S2", "P2"

    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": "ok"}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return _Resp()

    import llm as llm_mod
    monkeypatch.setattr(llm_mod.requests, "post", fake_post)

    obj = LLM(compressor=_Stub())
    out = obj.generate("original prompt", system="original system", use_cache=False)
    assert out == "ok"
    assert seen["system"] == "original system"
    assert seen["prompt"] == "original prompt"
    assert seen["json_mode"] is False
    # The compressed values must be what reaches Ollama
    assert captured["payload"]["prompt"] == "P2"
    assert captured["payload"]["system"] == "S2"


def test_llm_no_compressor_unchanged(monkeypatch):
    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": "ok"}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return _Resp()

    import llm as llm_mod
    monkeypatch.setattr(llm_mod.requests, "post", fake_post)

    obj = LLM()  # no compressor
    obj.generate("hello", system="sys", use_cache=False)
    assert captured["payload"]["prompt"] == "hello"
    assert captured["payload"]["system"] == "sys"


# ---------- Dashboard endpoint ----------

def test_dashboard_compression_endpoint(tmp_path, monkeypatch):
    import dashboard.app as dapp
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()
    log = out_dir / "compression_log.jsonl"
    log.write_text(
        json.dumps({"tokens_before": 500, "tokens_after": 50}) + "\n"
        + json.dumps({"tokens_before": 1000, "tokens_after": 200}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(dapp, "OUTPUTS_DIR", out_dir)

    client = dapp.app.test_client()
    rv = client.get("/api/compression")
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["calls"] == 2
    assert data["tokens_before"] == 1500
    assert data["tokens_after"] == 250
    assert data["tokens_saved"] == 1250
    assert 0.83 < data["compression_ratio"] < 0.84
