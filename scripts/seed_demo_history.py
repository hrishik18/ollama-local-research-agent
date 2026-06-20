"""Create a few synthetic iterations so the dashboard has something to show
before you've actually run the agent end-to-end. Safe to run multiple times —
it only writes if no real iterations exist.

Usage:
    python scripts/seed_demo_history.py [--force]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.benchmark import score_iteration, write_scorecard  # noqa: E402


DEMO_ITERATIONS = [
    {
        "n": 1, "steps": 25, "elapsed_min": 18.4, "sections": 1, "sources": 2,
        "tool_usage": {"web_search": 8, "memory_search": 3, "synthesize": 1},
        "tool_failures": {"web_search": 2},
        "skills_used": [],
        "done": False, "shutdown_reason": "budget_steps",
        "final": (
            "# Introduction\n\n"
            "Initial draft on the topic with limited depth (https://example.com/intro). "
            "More work needed [src_a].\n"
        ),
    },
    {
        "n": 2, "steps": 42, "elapsed_min": 32.1, "sections": 3, "sources": 5,
        "tool_usage": {"web_search": 10, "arxiv_search": 4, "memory_search": 8,
                       "synthesize": 2, "use_skill": 3},
        "tool_failures": {"web_search": 1},
        "skills_used": ["summarize_chunks", "extract_paper_findings", "summarize_chunks"],
        "done": True, "shutdown_reason": "done",
        "final": (
            "# Introduction\n\nExpanded intro with proper grounding [src_a] (https://example.com/a).\n\n"
            "# Method\n\nReviewed core approaches [src_b] (https://arxiv.org/abs/1234).\n\n"
            "# Findings\n\nKey results [src_c] [src_d] and (https://example.com/d).\n"
        ),
    },
    {
        "n": 3, "steps": 58, "elapsed_min": 45.3, "sections": 5, "sources": 9,
        "tool_usage": {"web_search": 9, "arxiv_search": 6, "semantic_scholar": 3,
                       "github_search": 2, "memory_search": 12, "synthesize": 4,
                       "use_skill": 6, "pdf_reader": 3, "hacker_news": 1},
        "tool_failures": {"pdf_reader": 1},
        "skills_used": ["summarize_chunks", "extract_paper_findings", "compare_approaches",
                        "critique_section", "find_contradictions", "evaluate_progress"],
        "done": True, "shutdown_reason": "done",
        "final": (
            "# Introduction\n\nFull-context intro [src_a] [src_b].\n\n"
            "# Background\n\nHistorical context [src_c] (https://example.com/c).\n\n"
            "# Method\n\nMethodology comparison [src_d] [src_e] (https://arxiv.org/abs/5678).\n\n"
            "# Findings\n\nKey insights with citations [src_f] [src_g] [src_h] [src_i].\n\n"
            "# Conclusion\n\nSynthesis [src_a] [src_e] (https://example.com/final).\n"
        ),
    },
]


def write_iteration(history_dir: Path, log_path: Path, spec: dict, start_ts: float) -> None:
    n = spec["n"]
    iter_dir = history_dir / f"iteration_{n:03d}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    (iter_dir / "final.md").write_text(spec["final"], encoding="utf-8")
    sections = [f"Section {i}" for i in range(spec["sections"])]
    summary = (
        f"# Iteration {n}\n\n"
        f"- ts: 2026-06-20T0{n}:00:00Z\n"
        f"- steps: {spec['steps']}/500\n"
        f"- elapsed_min: {spec['elapsed_min']}\n"
        f"- done: {spec['done']}\n"
        f"- shutdown_reason: {spec['shutdown_reason']}\n"
        f"- sections_written: {json.dumps(sections)}\n"
        f"- tool_usage: {json.dumps(spec['tool_usage'])}\n"
        f"- tool_failures: {json.dumps(spec['tool_failures'])}\n"
    )
    (iter_dir / "summary.md").write_text(summary, encoding="utf-8")
    (iter_dir / "prompt.md").write_text(f"GOAL: demo iteration {n}\n", encoding="utf-8")

    # Append synthetic agent_log events for this iteration
    with open(log_path, "a", encoding="utf-8") as f:
        step = 0
        for tool, count in spec["tool_usage"].items():
            for _ in range(count):
                step += 1
                action = {"tool": tool, "args": {}, "thought": f"using {tool} at step {step}"}
                if tool == "use_skill" and spec["skills_used"]:
                    skill_name = spec["skills_used"][min(step % len(spec["skills_used"]),
                                                         len(spec["skills_used"]) - 1)]
                    action["args"] = {"name": skill_name, "vars": {}}
                f.write(json.dumps({
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                        time.gmtime(start_ts + step * 30)),
                    "type": "step",
                    "step": step,
                    "iteration": n,
                    "action": action,
                    "summary": f"{tool} executed",
                    "duration_s": round(1.5 + (step % 7) * 0.4, 2),
                }) + "\n")
        # A couple of reflections
        for r_step in (step // 2, step):
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                    time.gmtime(start_ts + r_step * 30 + 5)),
                "type": "reflect",
                "step": r_step,
                "iteration": n,
                "result": {"assessment": f"iter {n} reflection at step {r_step}",
                           "next_actions": "continue with more depth"},
            }) + "\n")


def write_system_metrics(outputs: Path) -> None:
    p = outputs / "system_metrics.jsonl"
    if p.exists():
        return
    now = time.time()
    with open(p, "w", encoding="utf-8") as f:
        for i in range(40):
            ts = now - (40 - i) * 60
            ram = 45 + (i * 0.8) + ((i % 5) * 2)
            cpu = 30 + ((i * 3) % 50)
            temp = 55 + (i * 0.4) + ((i % 7) * 1.5)
            f.write(json.dumps({
                "ts": ts,
                "ram_pct": round(min(ram, 92), 1),
                "cpu_pct": round(cpu, 1),
                "proc_rss_mb": round(180 + i * 1.5, 1),
                "max_temp_c": round(min(temp, 88), 1),
            }) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="Overwrite even if real iterations exist")
    ap.add_argument("--history", default=str(ROOT / "history"))
    ap.add_argument("--outputs", default=str(ROOT / "outputs"))
    args = ap.parse_args()

    history_dir = Path(args.history)
    outputs_dir = Path(args.outputs)
    history_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    existing = list(history_dir.glob("iteration_*"))
    if existing and not args.force:
        print(f"Found {len(existing)} existing iteration(s). Use --force to overwrite. Skipping.")
        return

    log_path = outputs_dir / "agent_log.jsonl"
    if args.force and log_path.exists():
        log_path.unlink()

    start_ts = time.time() - 3 * 60 * 60  # 3 hours ago

    for i, spec in enumerate(DEMO_ITERATIONS):
        write_iteration(history_dir, log_path, spec, start_ts + i * 3600)

    # Score them
    prev = None
    for spec in DEMO_ITERATIONS:
        iter_dir = history_dir / f"iteration_{spec['n']:03d}"
        sc = score_iteration(iter_dir, agent_log_path=log_path, prev=prev)
        write_scorecard(iter_dir, sc)
        prev = sc
        print(f"  scored {sc['iteration']}: composite={sc['composite_score']:.1f} "
              f"(sections={sc['n_sections']}, sources={sc['n_unique_sources']}, "
              f"tools={sc['tool_diversity']}, skills={sc['skill_diversity']})")

    write_system_metrics(outputs_dir)

    # Write a demo final.md
    final_path = outputs_dir / "final.md"
    if not final_path.exists() or args.force:
        final_path.write_text(DEMO_ITERATIONS[-1]["final"] +
                              "\n---\n_Demo data — run main.py for real iterations._\n",
                              encoding="utf-8")
    print(f"\nDone. Open http://localhost:5050 (after `python dashboard/app.py`).")


if __name__ == "__main__":
    main()
