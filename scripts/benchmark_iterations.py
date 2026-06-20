"""Backfill / refresh benchmark scorecards across all iterations.

Usage:
    python scripts/benchmark_iterations.py
    python scripts/benchmark_iterations.py --history history --log outputs/agent_log.jsonl
    python scripts/benchmark_iterations.py --print

Writes:
    history/iteration_NNN/scorecard.json   (per iteration)
    history/benchmark_report.json          (roll-up with all + deltas)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.benchmark import score_all, write_scorecard  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default=str(ROOT / "history"))
    ap.add_argument("--log", default=str(ROOT / "outputs" / "agent_log.jsonl"))
    ap.add_argument("--print", action="store_true", help="print summary to stdout")
    args = ap.parse_args()

    history_dir = Path(args.history)
    log_path = Path(args.log)

    if not history_dir.exists():
        print(f"No history dir at {history_dir}", file=sys.stderr)
        sys.exit(1)

    results = score_all(history_dir, agent_log_path=log_path if log_path.exists() else None)

    for sc in results:
        iter_dir = history_dir / sc["iteration"]
        write_scorecard(iter_dir, sc)

    report_path = history_dir / "benchmark_report.json"
    report_path.write_text(
        json.dumps({"iterations": results}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Scored {len(results)} iteration(s). Report: {report_path}")
    if args.print:
        for sc in results:
            d = sc.get("delta_vs_prev", {})
            arrow = "" if not d else (
                f" | Δscore: {d.get('composite_score', 0):+.1f}"
            )
            print(
                f"  {sc['iteration']:<16} "
                f"score={sc['composite_score']:>5.1f}  "
                f"chars={sc['output_chars']:>5}  "
                f"sections={sc['n_sections']:>2}  "
                f"sources={sc['n_unique_sources']:>2}  "
                f"tools={sc['tool_diversity']:>2}  "
                f"skills={sc['skill_diversity']:>2}"
                f"{arrow}"
            )


if __name__ == "__main__":
    main()
