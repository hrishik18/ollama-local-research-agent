"""Deterministic per-iteration benchmark scoring.

For each `history/iteration_NNN/` directory, compute a scorecard of objective metrics
that lets you answer the question:

    "Was iteration N actually better than iteration N-1?"

The scorer is intentionally OFFLINE and deterministic — it reads the files the agent
already writes (summary.md, final.md, agent_log.jsonl filtered by iteration) and emits
numbers. No LLM calls, no network. For an LLM-judge style qualitative score, see the
`score_iteration` skill — it's separate and opt-in.

Public API:
    score_iteration(iter_dir, agent_log_path=None, prev=None) -> dict
    score_all(history_dir, agent_log_path=None) -> list[dict]
    composite_score(metrics: dict) -> float
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

# Citation regexes — recognise [source_id], [src:...], and bare https URLs
_CITATION_RE = re.compile(r"\[([^\[\]\n]{2,80})\]|\((https?://[^\s)]+)\)|\bhttps?://[^\s)]+")
_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
_SUMMARY_BULLET_RE = re.compile(r"^-\s+(\w+):\s+(.+)$", re.MULTILINE)


# ---------- file readers ----------

def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _parse_summary(text: str) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for m in _SUMMARY_BULLET_RE.finditer(text):
        key, val = m.group(1), m.group(2).strip()
        try:
            meta[key] = json.loads(val)
        except (json.JSONDecodeError, TypeError, ValueError):
            meta[key] = val
    return meta


def _iter_log_events(log_path: Path, iteration: int) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    out = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("iteration") == iteration:
            out.append(ev)
    return out


# ---------- metric calculators ----------

def _output_metrics(final_md: str) -> dict[str, Any]:
    if not final_md:
        return {
            "output_chars": 0, "output_words": 0, "n_sections": 0,
            "n_citations": 0, "n_unique_sources": 0, "avg_section_chars": 0.0,
        }
    headings = _HEADING_RE.findall(final_md)
    citations = _CITATION_RE.findall(final_md)
    # citations is list of tuples (group1, group2) — flatten and dedupe
    flat: list[str] = []
    for c in citations:
        if isinstance(c, tuple):
            for g in c:
                if g:
                    flat.append(g)
        elif c:
            flat.append(c)
    n_sections = max(len(headings), 1)
    return {
        "output_chars": len(final_md),
        "output_words": len(final_md.split()),
        "n_sections": len(headings),
        "n_citations": len(flat),
        "n_unique_sources": len(set(flat)),
        "avg_section_chars": round(len(final_md) / n_sections, 1),
    }


def _tool_metrics(summary: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    tool_usage = summary.get("tool_usage") or {}
    if isinstance(tool_usage, str):
        try:
            tool_usage = json.loads(tool_usage)
        except json.JSONDecodeError:
            tool_usage = {}
    tool_failures = summary.get("tool_failures") or {}
    if isinstance(tool_failures, str):
        try:
            tool_failures = json.loads(tool_failures)
        except json.JSONDecodeError:
            tool_failures = {}

    total_calls = sum(tool_usage.values()) if tool_usage else 0
    total_fails = sum(tool_failures.values()) if tool_failures else 0

    # Skill usage: pull from agent_log step events with tool == "use_skill"
    skill_counter: Counter[str] = Counter()
    durations: list[float] = []
    reflect_count = 0
    for ev in events:
        if ev.get("type") == "step":
            action = ev.get("action", {}) or {}
            if action.get("tool") == "use_skill":
                name = (action.get("args") or {}).get("name") or "(unknown)"
                skill_counter[name] += 1
            d = ev.get("duration_s")
            if isinstance(d, (int, float)):
                durations.append(d)
        elif ev.get("type") == "reflect":
            reflect_count += 1

    return {
        "total_tool_calls": total_calls,
        "total_tool_failures": total_fails,
        "tool_success_ratio": round(
            (total_calls - total_fails) / total_calls, 3
        ) if total_calls else 0.0,
        "tool_diversity": len(tool_usage),
        "tool_usage": dict(tool_usage),
        "tool_failures": dict(tool_failures),
        "skill_usage": dict(skill_counter),
        "n_skill_calls": sum(skill_counter.values()),
        "skill_diversity": len(skill_counter),
        "n_reflections": reflect_count,
        "avg_step_duration_s": round(sum(durations) / len(durations), 2) if durations else 0.0,
        "p95_step_duration_s": round(_percentile(durations, 95), 2) if durations else 0.0,
    }


def _efficiency_metrics(summary: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    steps = _coerce_int(summary.get("steps")) or _coerce_steps(summary.get("steps"))
    elapsed = _coerce_float(summary.get("elapsed_min"))
    n_sections = output["n_sections"]
    return {
        "steps": steps,
        "elapsed_min": elapsed,
        "steps_per_section": round(steps / n_sections, 2) if n_sections else 0.0,
        "chars_per_minute": round(output["output_chars"] / elapsed, 1) if elapsed else 0.0,
        "citations_per_section": round(output["n_citations"] / n_sections, 2) if n_sections else 0.0,
    }


def _coerce_int(v: Any) -> int:
    try:
        if isinstance(v, str) and "/" in v:
            return int(v.split("/")[0])
        return int(v)
    except (TypeError, ValueError):
        return 0


def _coerce_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _coerce_steps(v: Any) -> int:
    if isinstance(v, str) and "/" in v:
        return _coerce_int(v.split("/")[0])
    return _coerce_int(v)


def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = max(0, min(len(s) - 1, int(len(s) * p / 100)))
    return s[k]


# ---------- composite score ----------

# Weights chosen so a healthy run sits around 50-70, an excellent run 80+, a broken
# run < 30. These are heuristic — tune as needed.
COMPOSITE_WEIGHTS = {
    "output_chars": (1500, 15),         # ~1.5k chars target, max 15 pts
    "n_sections": (3, 10),              # 3 sections target, max 10
    "n_unique_sources": (5, 15),        # 5 distinct sources, max 15
    "citations_per_section": (2.0, 10), # 2 citations/section, max 10
    "tool_diversity": (4, 10),          # 4 distinct tools, max 10
    "tool_success_ratio": (1.0, 15),    # ratio in [0,1] * 15
    "skill_diversity": (2, 10),         # 2 distinct skills, max 10
    "n_reflections": (2, 5),            # 2 reflections, max 5
    "shutdown_done": (1, 10),           # done = 10, anything else = 0
}


def composite_score(metrics: dict[str, Any]) -> float:
    score = 0.0
    for key, (target, weight) in COMPOSITE_WEIGHTS.items():
        if key == "shutdown_done":
            v = 1.0 if metrics.get("shutdown_reason") in ("(none)", "done", None) and metrics.get("done") else 0.0
            score += v * weight
            continue
        val = _coerce_float(metrics.get(key, 0))
        score += min(val / target, 1.0) * weight if target else 0.0
    return round(score, 1)


# ---------- public API ----------

def score_iteration(
    iter_dir: Path,
    agent_log_path: Path | None = None,
    prev: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary_text = _read(iter_dir / "summary.md")
    final_text = _read(iter_dir / "final.md")
    summary = _parse_summary(summary_text)

    # Determine iteration number
    iter_num = _coerce_int(re.sub(r"\D", "", iter_dir.name)) or 0

    events = _iter_log_events(agent_log_path, iter_num) if agent_log_path else []

    output = _output_metrics(final_text)
    tools_m = _tool_metrics(summary, events)
    eff = _efficiency_metrics(summary, output)

    metrics: dict[str, Any] = {
        "iteration": iter_dir.name,
        "iteration_num": iter_num,
        "ts": summary.get("ts"),
        "done": (summary.get("done") in (True, "True", "true")),
        "shutdown_reason": summary.get("shutdown_reason"),
        **output,
        **tools_m,
        **eff,
    }
    metrics["composite_score"] = composite_score(metrics)

    if prev:
        metrics["delta_vs_prev"] = _deltas(metrics, prev)

    return metrics


def _deltas(cur: dict[str, Any], prev: dict[str, Any]) -> dict[str, float]:
    keys = [
        "output_chars", "n_sections", "n_unique_sources", "n_citations",
        "tool_diversity", "tool_success_ratio", "skill_diversity",
        "composite_score", "avg_step_duration_s", "elapsed_min",
    ]
    out: dict[str, float] = {}
    for k in keys:
        a = _coerce_float(cur.get(k))
        b = _coerce_float(prev.get(k))
        out[k] = round(a - b, 3)
    return out


def score_all(history_dir: Path, agent_log_path: Path | None = None) -> list[dict[str, Any]]:
    iters = sorted(
        [d for d in history_dir.glob("iteration_*") if d.is_dir()],
        key=lambda p: p.name,
    )
    results: list[dict[str, Any]] = []
    prev: dict[str, Any] | None = None
    for d in iters:
        sc = score_iteration(d, agent_log_path=agent_log_path, prev=prev)
        results.append(sc)
        prev = sc
    return results


def write_scorecard(iter_dir: Path, scorecard: dict[str, Any]) -> Path:
    path = iter_dir / "scorecard.json"
    path.write_text(json.dumps(scorecard, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
