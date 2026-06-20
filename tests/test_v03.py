"""Smoke tests for v0.3 additions: new tools, new skills, dashboard parsing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure repo root is on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_imports_new_tools():
    from tools import HackerNewsTool, RssTool, GithubSearchTool, maybe_setup_phoenix  # noqa: F401


def test_phoenix_disabled_by_default():
    from tools import maybe_setup_phoenix
    assert maybe_setup_phoenix({}) is False
    assert maybe_setup_phoenix({"tracing": {"enabled": False}}) is False


def test_hn_tool_constructible():
    from tools import HackerNewsTool
    t = HackerNewsTool(max_results=5)
    assert t.name == "hacker_news"
    assert "Hacker News" in t.description


def test_rss_tool_constructible():
    from tools import RssTool
    t = RssTool(max_entries=5)
    assert t.name == "rss"


def test_github_tool_constructible():
    from tools import GithubSearchTool
    t = GithubSearchTool(max_results=5)
    assert t.name == "github_search"
    # Headers must be a dict containing Accept
    assert "Accept" in t.headers


def test_new_skills_present():
    from tools.skills import SkillRegistry

    class _StubLLM:
        def generate(self, *a, **kw):
            return "{}"
        def generate_json(self, *a, **kw):
            return {}

    reg = SkillRegistry(_StubLLM(), skills_dir=str(ROOT / "skills"))
    names = set(reg.skills.keys())
    for n in ("critique_section", "find_contradictions", "generate_search_queries"):
        assert n in names, f"missing new skill: {n}"


def test_dashboard_module_imports():
    import importlib.util
    spec = importlib.util.spec_from_file_location("dashboard_app", ROOT / "dashboard" / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "app")
    assert hasattr(mod, "list_iterations")
    assert hasattr(mod, "load_system_metrics")


def test_dashboard_summary_parsing(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("dashboard_app", ROOT / "dashboard" / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Create a fake iteration directory
    fake_history = tmp_path / "history"
    iter_dir = fake_history / "iteration_001"
    iter_dir.mkdir(parents=True)
    (iter_dir / "summary.md").write_text(
        "# Iteration\n"
        "- steps: 42\n"
        "- elapsed_min: 5.3\n"
        '- tool_usage: {"web_search": 3, "memory_search": 2}\n'
        '- sections_written: ["intro", "findings"]\n'
        "- shutdown_reason: done\n",
        encoding="utf-8",
    )
    (iter_dir / "final.md").write_text("# Final\nHello", encoding="utf-8")

    monkeypatch.setattr(mod, "HISTORY_DIR", fake_history)
    iters = mod.list_iterations()
    assert len(iters) == 1
    it = iters[0]
    assert it["iteration"] == "iteration_001"
    assert it["steps"] == 42
    assert it["tool_usage"] == {"web_search": 3, "memory_search": 2}
    assert it["sections_written"] == ["intro", "findings"]
    assert it["has_final"] is True


def test_dashboard_metrics_parsing(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("dashboard_app", ROOT / "dashboard" / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    outputs = tmp_path / "outputs"
    outputs.mkdir()
    metrics = outputs / "system_metrics.jsonl"
    metrics.write_text(
        "\n".join([
            json.dumps({"ts": 1000, "ram_pct": 50.0, "cpu_pct": 10.0, "proc_rss_mb": 200, "max_temp_c": 55.0}),
            json.dumps({"ts": 1030, "ram_pct": 60.0, "cpu_pct": 80.0, "proc_rss_mb": 250, "max_temp_c": 62.0}),
            "not-json-skip",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "OUTPUTS_DIR", outputs)
    rows = mod.load_system_metrics()
    assert len(rows) == 2
    assert rows[0]["ram_pct"] == 50.0
    assert rows[1]["max_temp_c"] == 62.0


def test_dashboard_routes_exist():
    import importlib.util
    spec = importlib.util.spec_from_file_location("dashboard_app", ROOT / "dashboard" / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    client = mod.app.test_client()
    # All API routes should return 200 even when files are missing
    for route in ("/api/iterations", "/api/system-metrics", "/api/agent-log",
                  "/api/experiments", "/api/skills"):
        resp = client.get(route)
        assert resp.status_code == 200, f"{route} returned {resp.status_code}"


def test_config_has_new_sections():
    import yaml
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    assert "tracing" in cfg
    assert cfg["tracing"]["enabled"] is False
    for key in ("hacker_news", "rss", "github_search"):
        assert key in cfg["tools"], f"missing tools.{key} in config.yaml"
