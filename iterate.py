"""Multi-iteration runner.

Runs main.py repeatedly. Between iterations:
1. Reads the last iteration's summary
2. Invokes the `improve_prompt` skill to evolve prompt.md
3. Bumps the iteration counter
4. Optionally clears state (memory) — by default state is preserved across iterations

Usage:
    python iterate.py --n 3 --hours-per-iter 4
    python iterate.py --n 5 --hours-per-iter 2 --fresh-state
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from rich.console import Console
from rich.logging import RichHandler

from llm import LLM
from tools import DiskCache, SkillRegistry, build_compressor

console = Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=console, markup=True)],
)
log = logging.getLogger("iterate")


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def evolve_prompt(config: dict) -> None:
    """Run the improve_prompt skill against the last iteration."""
    history_dir = Path(config["paths"]["history_dir"])
    prompt_file = Path(config["paths"]["prompt_file"])
    iter_dirs = sorted(history_dir.glob("iteration_*"))
    if not iter_dirs:
        log.info("No previous iterations — skipping prompt evolution.")
        return
    last = iter_dirs[-1]

    cache = None
    if config.get("cache", {}).get("enabled", True):
        cache = DiskCache(config["cache"]["dir"], config["cache"]["ttl_seconds"])

    # Parity with main.py — use the same headroom-ai prompt compressor for
    # the prompt-evolution call. Saves tokens on the long summary+output context.
    default_clog = config.get("paths", {}).get(
        "compression_log", "outputs/compression_log.jsonl"
    )
    compressor = build_compressor(config, default_log_path=default_clog)

    llm_cfg = config["llm"]
    llm = LLM(
        model=llm_cfg["model"],
        embed_model=llm_cfg["embed_model"],
        host=llm_cfg["host"],
        timeout=llm_cfg["request_timeout"],
        max_tokens=llm_cfg["max_tokens"],
        keep_alive=llm_cfg.get("keep_alive", "30m"),
        cache=cache,
        compressor=compressor,
    )

    if not llm.health_check():
        log.warning("Ollama unreachable — skipping prompt evolution.")
        return

    skills = SkillRegistry(llm, skills_dir=config["paths"]["skills_dir"])

    current_prompt = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else ""
    last_summary = (last / "summary.md").read_text(encoding="utf-8") if (last / "summary.md").exists() else ""
    final_md = last / "final.md"
    output_preview = final_md.read_text(encoding="utf-8")[:2000] if final_md.exists() else ""

    # v0.4+: include the deterministic scorecard so the LLM can see concrete
    # numbers (composite score, deltas vs. previous iteration) when proposing
    # prompt edits. Falls back silently for pre-v0.4 history dirs.
    scorecard_path = last / "scorecard.json"
    scorecard_summary = ""
    if scorecard_path.exists():
        try:
            import json as _json
            sc = _json.loads(scorecard_path.read_text(encoding="utf-8"))
            composite = sc.get("composite_score") or sc.get("composite") or "?"
            delta = sc.get("delta_vs_prev") or {}
            scorecard_summary = (
                f"\n\nLast iteration scorecard:\n"
                f"  composite_score: {composite}/100\n"
                f"  delta_vs_prev:   {delta}\n"
            )
            last_summary = (last_summary + scorecard_summary)[:3500]
        except Exception as e:
            log.debug("could not parse scorecard.json: %s", e)

    try:
        result = llm.generate_json(
            skills.skills["improve_prompt"]["template"].format(
                current_prompt=current_prompt,
                last_run_summary=last_summary[:3000],
                output_preview=output_preview,
            ),
            temperature=0.3,
        )
    except Exception as e:
        log.warning("Prompt evolution skill failed: %s", e)
        return

    learnings = result.get("learnings_to_append", "")
    edits = result.get("edits", [])
    rationale = result.get("rationale", "")

    log.info("[cyan]Prompt evolution proposed:[/cyan]")
    log.info("  rationale: %s", rationale)
    for e in edits:
        log.info("  - %s", e)

    # Append learnings + edits to prompt.md
    if prompt_file.exists():
        text = prompt_file.read_text(encoding="utf-8")
        marker = "<!-- The agent appends concise lessons from each iteration below this line. -->"
        addition = (
            f"\n\n### Auto-evolved {datetime.now(timezone.utc).date()}\n"
            f"_Rationale: {rationale}_\n\n"
            + "\n".join(f"- {e}" for e in edits)
            + (f"\n\n{learnings}\n" if learnings else "\n")
        )
        if marker in text:
            text = text.replace(marker, marker + addition)
        else:
            text += addition
        prompt_file.write_text(text, encoding="utf-8")
        log.info("prompt.md updated with %d edits + learnings.", len(edits))


def reset_state(config: dict) -> None:
    state_dir = Path(config["paths"]["state_dir"])
    if state_dir.exists():
        shutil.rmtree(state_dir)
        log.info("Cleared %s", state_dir)
    outputs = Path(config["paths"]["final_output"])
    if outputs.exists():
        outputs.unlink()
        log.info("Cleared %s", outputs)


def run_one_iteration(hours: float, steps: int | None) -> int:
    cmd = [sys.executable, "main.py", "--hours", str(hours)]
    if steps:
        cmd += ["--steps", str(steps)]
    log.info("[bold green]→ Running: %s[/bold green]", " ".join(cmd))
    return subprocess.call(cmd)


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-iteration runner.")
    parser.add_argument("--n", type=int, default=3, help="Number of iterations.")
    parser.add_argument("--hours-per-iter", type=float, default=4.0)
    parser.add_argument("--steps-per-iter", type=int, default=None)
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("--fresh-state", action="store_true",
                        help="Clear FAISS index + output between iterations.")
    parser.add_argument("--no-evolve", action="store_true",
                        help="Skip the prompt evolution step between iterations.")
    args = parser.parse_args()

    config = load_config(args.config)

    for i in range(args.n):
        log.info("[bold magenta]===== Iteration %d/%d =====[/bold magenta]", i + 1, args.n)
        if args.fresh_state and i > 0:
            reset_state(config)

        rc = run_one_iteration(args.hours_per_iter, args.steps_per_iter)
        if rc != 0:
            log.error("Iteration exited with code %d — stopping.", rc)
            break

        if not args.no_evolve and i < args.n - 1:
            log.info("[yellow]Evolving prompt.md based on iteration %d...[/yellow]", i + 1)
            evolve_prompt(config)

    log.info("[bold green]All iterations complete.[/bold green]")


if __name__ == "__main__":
    main()
