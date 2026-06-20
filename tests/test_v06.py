"""v0.6 tests: BrowserTool (Playwright) graceful fallback + skill.

These tests do NOT require Playwright to be installed. They verify:
1. BrowserTool returns clear error when disabled.
2. BrowserTool returns clear error when Playwright is missing.
3. Disabled tool never crashes; fields are well-formed.
4. browser_automation skill is discoverable by the skill registry.
5. Skill metadata follows the repo's `USE WHEN` + `## TEMPLATE` convention.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.browser import BrowserTool  # noqa: E402
import tools.browser as browser_mod  # noqa: E402


def test_disabled_fetch_returns_error_without_crashing():
    t = BrowserTool(enabled=False)
    r = t.fetch("https://example.com")
    assert r["url"] == "https://example.com"
    assert "disabled" in r["error"].lower()
    assert r["text"] == ""


def test_disabled_extract_and_screenshot():
    t = BrowserTool(enabled=False)
    r1 = t.extract("https://example.com", ["h1"])
    r2 = t.screenshot("https://example.com")
    assert "error" in r1
    assert "error" in r2


def test_enabled_but_playwright_missing(monkeypatch):
    """Enabled tool returns the install hint, never crashes."""
    monkeypatch.setattr(browser_mod, "_PW_AVAILABLE", False)
    monkeypatch.setattr(browser_mod, "_check_playwright", lambda: False)
    t = BrowserTool(enabled=True)
    r = t.fetch("https://example.com")
    assert "playwright" in r["error"].lower()
    assert "pip install" in r["error"]


def test_run_dispatch():
    """The generic .run() dispatcher routes to the right action."""
    t = BrowserTool(enabled=False)
    r_fetch = t.run("https://example.com")
    r_extract = t.run("https://example.com", action="extract", css_selectors=["h1"])
    r_shot = t.run("https://example.com", action="screenshot")
    # All disabled → all return error, but the right shape for each action.
    assert r_fetch["error"] and "text" in r_fetch
    assert r_extract["error"]
    assert r_shot["error"]


def test_browser_skill_file_exists_and_well_formed():
    skill = ROOT / "skills" / "browser_automation.md"
    assert skill.exists(), "browser_automation.md skill should be shipped"
    content = skill.read_text(encoding="utf-8")
    assert "USE WHEN" in content
    assert "## TEMPLATE" in content
    # The skill must reference the actual tool name the agent calls.
    assert "browser" in content.lower()
    # Must have the required template placeholders the orchestrator will fill.
    for placeholder in ("{url}", "{title}", "{text}", "{goal}", "{reason}"):
        assert placeholder in content, f"missing placeholder {placeholder}"


def test_browser_skill_loads_in_registry():
    """The existing SkillRegistry should pick up the new skill at startup."""
    from tools.skills import SkillRegistry

    class _StubLLM:
        def generate(self, prompt, system=None, **k):
            return "{}"

    reg = SkillRegistry(_StubLLM(), skills_dir=str(ROOT / "skills"))
    reg.load()
    assert "browser_automation" in reg.skills


def test_screenshot_dir_is_created(tmp_path):
    sd = tmp_path / "shots_subdir"
    BrowserTool(enabled=False, screenshot_dir=str(sd))
    assert sd.exists() and sd.is_dir()


# ---------- self-heal regression tests ----------

def test_synthesizer_uses_config_temperature():
    """v0.6 self-heal: tools.synthesizer.SynthesizerTool must honour the
    `temperature` constructor arg (config.llm.temperature_synth was previously
    silently ignored — hardcoded to 0.5)."""
    from tools.synthesizer import SynthesizerTool

    captured = {}

    class _LLM:
        def generate(self, prompt, system=None, temperature=None, **k):
            captured["temperature"] = temperature
            return "x"

    class _Mem:
        def search(self, q, top_k=8):
            return [{"text": "t", "meta": {"source": "s1"}}]

    t = SynthesizerTool(_LLM(), _Mem(), temperature=0.77)
    t.run("topic")
    assert captured["temperature"] == 0.77


def test_main_module_has_no_utcnow_calls():
    """v0.6 self-heal: every datetime.utcnow() use is gone (Py3.13 deprecated)."""
    import re
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    # Strip comments before grepping
    no_comments = re.sub(r"#.*$", "", src, flags=re.M)
    assert "datetime.utcnow" not in no_comments, "main.py still calls datetime.utcnow()"

    src2 = (ROOT / "iterate.py").read_text(encoding="utf-8")
    no_comments2 = re.sub(r"#.*$", "", src2, flags=re.M)
    assert "datetime.utcnow" not in no_comments2, "iterate.py still calls datetime.utcnow()"


def test_iterate_imports_build_compressor():
    """v0.6 self-heal: iterate.py must build LLM with the same compressor wiring as main.py."""
    src = (ROOT / "iterate.py").read_text(encoding="utf-8")
    assert "build_compressor" in src
    assert "compressor=compressor" in src

