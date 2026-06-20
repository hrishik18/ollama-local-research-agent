"""Tests for v0.4 benchmark scoring + enhanced dashboard."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.benchmark import (  # noqa: E402
    composite_score,
    score_all,
    score_iteration,
    write_scorecard,
)


def _make_iter(tmp: Path, n: int, *, sections: int = 2, sources: int = 3,
               tool_usage: dict | None = None, tool_failures: dict | None = None,
               done: bool = True, steps: int = 30, elapsed_min: float = 12.5) -> Path:
    d = tmp / f"iteration_{n:03d}"
    d.mkdir(parents=True, exist_ok=True)
    final_lines = [f"# Section {i}\nClaim {i} [src_{i % sources}] and (https://example.com/{i})."
                   for i in range(sections)]
    (d / "final.md").write_text("\n\n".join(final_lines), encoding="utf-8")
    (d / "summary.md").write_text(
        f"# Iteration {n}\n"
        f"- ts: 2026-06-20T00:00:00Z\n"
        f"- steps: {steps}/500\n"
        f"- elapsed_min: {elapsed_min}\n"
        f"- done: {done}\n"
        f"- shutdown_reason: {'done' if done else 'budget'}\n"
        f"- sections_written: {json.dumps([f'Section {i}' for i in range(sections)])}\n"
        f"- tool_usage: {json.dumps(tool_usage or {'web_search': 3, 'memory_search': 2})}\n"
        f"- tool_failures: {json.dumps(tool_failures or {})}\n",
        encoding="utf-8",
    )
    return d


def _make_log(tmp: Path, events: list[dict]) -> Path:
    p = tmp / "agent_log.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    return p


def test_score_single_iteration(tmp_path):
    d = _make_iter(tmp_path, 1, sections=3, sources=2,
                   tool_usage={"web_search": 5, "arxiv_search": 2, "use_skill": 1},
                   tool_failures={"web_search": 1})
    log = _make_log(tmp_path, [
        {"type": "step", "iteration": 1, "step": 1, "duration_s": 2.5,
         "action": {"tool": "web_search"}},
        {"type": "step", "iteration": 1, "step": 2, "duration_s": 3.0,
         "action": {"tool": "use_skill", "args": {"name": "summarize_chunks"}}},
        {"type": "reflect", "iteration": 1, "step": 3, "result": {"assessment": "ok"}},
    ])
    sc = score_iteration(d, agent_log_path=log)
    assert sc["iteration"] == "iteration_001"
    assert sc["iteration_num"] == 1
    assert sc["n_sections"] == 3
    assert sc["output_chars"] > 0
    assert sc["n_unique_sources"] >= 2
    assert sc["tool_diversity"] == 3
    assert sc["total_tool_calls"] == 8
    assert sc["total_tool_failures"] == 1
    assert sc["tool_success_ratio"] == round(7/8, 3)
    assert sc["skill_usage"] == {"summarize_chunks": 1}
    assert sc["skill_diversity"] == 1
    assert sc["n_skill_calls"] == 1
    assert sc["n_reflections"] == 1
    assert sc["avg_step_duration_s"] > 0
    assert 0 <= sc["composite_score"] <= 100
    assert sc["done"] is True


def test_composite_score_bounds():
    perfect = {
        "output_chars": 100000, "n_sections": 50, "n_unique_sources": 50,
        "citations_per_section": 10, "tool_diversity": 20, "tool_success_ratio": 1.0,
        "skill_diversity": 10, "n_reflections": 10,
        "done": True, "shutdown_reason": "done",
    }
    assert composite_score(perfect) == 100.0

    broken = {
        "output_chars": 0, "n_sections": 0, "n_unique_sources": 0,
        "citations_per_section": 0, "tool_diversity": 0, "tool_success_ratio": 0,
        "skill_diversity": 0, "n_reflections": 0, "done": False,
        "shutdown_reason": "ram_abort",
    }
    assert composite_score(broken) == 0.0


def test_score_all_computes_deltas(tmp_path):
    _make_iter(tmp_path, 1, sections=2, sources=2)
    _make_iter(tmp_path, 2, sections=5, sources=5,
               tool_usage={"web_search": 5, "arxiv_search": 3, "wikipedia": 1})
    results = score_all(tmp_path)
    assert len(results) == 2
    assert "delta_vs_prev" not in results[0]
    d = results[1]["delta_vs_prev"]
    assert d["n_sections"] == 3            # 5 - 2
    assert d["n_unique_sources"] >= 0
    assert d["composite_score"] != 0       # iteration 2 should differ from 1


def test_write_scorecard_roundtrip(tmp_path):
    d = _make_iter(tmp_path, 1)
    sc = score_iteration(d)
    path = write_scorecard(d, sc)
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["iteration"] == "iteration_001"
    assert loaded["composite_score"] == sc["composite_score"]


def test_dashboard_new_endpoints(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("dashboard_app", ROOT / "dashboard" / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Seed history and outputs
    hist = tmp_path / "history"
    outs = tmp_path / "outputs"
    hist.mkdir(); outs.mkdir()
    d = _make_iter(hist, 1)
    sc = score_iteration(d)
    write_scorecard(d, sc)
    _make_iter(hist, 2, sections=4)
    write_scorecard(hist / "iteration_002", score_iteration(hist / "iteration_002", prev=sc))

    monkeypatch.setattr(mod, "HISTORY_DIR", hist)
    monkeypatch.setattr(mod, "OUTPUTS_DIR", outs)

    client = mod.app.test_client()
    cards = client.get("/api/scorecards").get_json()
    assert len(cards) == 2
    assert cards[1]["delta_vs_prev"]["n_sections"] != 0

    tools = client.get("/api/tool-heatmap").get_json()
    assert "tools" in tools and "matrix" in tools and "iterations" in tools

    iter_resp = client.get("/api/iteration/iteration_001").get_json()
    assert "scorecard" in iter_resp and "summary" in iter_resp and "timeline" in iter_resp

    # Path-traversal guard
    bad = client.get("/api/iteration/..%2Fetc")
    assert bad.status_code in (400, 404)


def test_dashboard_handles_missing_files(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("dashboard_app", ROOT / "dashboard" / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "HISTORY_DIR", tmp_path / "nope")
    monkeypatch.setattr(mod, "OUTPUTS_DIR", tmp_path / "nope")
    client = mod.app.test_client()
    for route in ("/api/scorecards", "/api/tool-heatmap", "/api/skill-heatmap",
                  "/api/experiments", "/api/system-metrics", "/api/agent-log"):
        r = client.get(route)
        assert r.status_code == 200, f"{route} returned {r.status_code}"
