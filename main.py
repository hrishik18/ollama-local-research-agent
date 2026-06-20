"""Autonomous research agent — orchestrator / ReAct loop.

Reads goal from `prompt.md` (or --prompt arg), runs an autonomous loop with system
monitoring, hybrid RAG memory, skills, and writes per-iteration history.

Usage:
    python main.py                                  # read goal from prompt.md
    python main.py --prompt prompts/example_goal.txt --hours 12
    python main.py --resume
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pickle
import re
import shutil
import signal
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.logging import RichHandler

from llm import LLM, LLMError
from prompts.templates import PLAN_PROMPT, REFLECT_PROMPT
from tools import (
    ArxivSearchTool,
    DiskCache,
    GithubSearchTool,
    HackerNewsTool,
    MemoryTool,
    PdfReaderTool,
    RssTool,
    SemanticScholarTool,
    SkillRegistry,
    SynthesizerTool,
    SystemMonitor,
    WebFetchTool,
    WebSearchTool,
    WikipediaTool,
    maybe_setup_phoenix,
)

console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=console, rich_tracebacks=True, markup=True)],
)
log = logging.getLogger("agent")


# ----------- Config loading -----------

def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ----------- prompt.md helpers -----------

_GOAL_RE = re.compile(r"##\s+GOAL\s*\n(.+?)(?=\n---|\n##\s+LEARNINGS)", re.DOTALL | re.IGNORECASE)
_ITER_RE = re.compile(r"current_iteration:\s*(\d+)", re.IGNORECASE)


def read_prompt_md(path: str) -> tuple[str, int]:
    """Return (goal_text, current_iteration) parsed from prompt.md."""
    p = Path(path)
    if not p.exists():
        return "", 0
    text = p.read_text(encoding="utf-8")
    m = _GOAL_RE.search(text)
    goal = m.group(1).strip() if m else text
    mi = _ITER_RE.search(text)
    iteration = int(mi.group(1)) if mi else 0
    return goal, iteration


def update_prompt_md(
    path: str,
    iteration: int,
    status: str,
    learnings_to_append: str = "",
) -> None:
    p = Path(path)
    if not p.exists():
        return
    text = p.read_text(encoding="utf-8")
    # Bump iteration counter
    text = re.sub(r"current_iteration:\s*\d+", f"current_iteration: {iteration}", text)
    text = re.sub(
        r"last_run_ts:\s*\S+",
        f"last_run_ts: {datetime.utcnow().isoformat()}Z",
        text,
    )
    text = re.sub(r"last_run_status:\s*\S+", f"last_run_status: {status}", text)
    # Append learnings if provided
    if learnings_to_append.strip():
        marker = "<!-- The agent appends concise lessons from each iteration below this line. -->"
        addition = (
            f"\n\n### Iteration {iteration} ({datetime.utcnow().date()})\n"
            f"{learnings_to_append.strip()}\n"
        )
        if marker in text:
            text = text.replace(marker, marker + addition)
        else:
            text += addition
    p.write_text(text, encoding="utf-8")


# ----------- Agent state -----------

class AgentState:
    def __init__(self, goal: str, max_steps: int, max_hours: float, iteration: int = 0) -> None:
        self.goal = goal
        self.iteration = iteration
        self.max_steps = max_steps
        self.max_seconds = max_hours * 3600
        self.start_time = time.time()
        self.step = 0
        self.notes = ""
        self.recent_actions: deque[dict[str, Any]] = deque(maxlen=10)
        self.sections_written: list[str] = []
        self.tool_failures: dict[str, int] = {}
        self.tool_usage: dict[str, int] = {}
        self.done = False

    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    def time_left(self) -> float:
        return max(0.0, self.max_seconds - self.elapsed_seconds())

    def out_of_budget(self) -> bool:
        return self.step >= self.max_steps or self.time_left() <= 0

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "iteration": self.iteration,
            "max_steps": self.max_steps,
            "max_seconds": self.max_seconds,
            "step": self.step,
            "notes": self.notes,
            "recent_actions": list(self.recent_actions),
            "sections_written": self.sections_written,
            "tool_failures": self.tool_failures,
            "tool_usage": self.tool_usage,
            "elapsed_at_save": self.elapsed_seconds(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AgentState":
        s = cls(d["goal"], d["max_steps"], d["max_seconds"] / 3600, d.get("iteration", 0))
        s.step = d["step"]
        s.notes = d["notes"]
        s.recent_actions = deque(d["recent_actions"], maxlen=10)
        s.sections_written = d["sections_written"]
        s.tool_failures = d["tool_failures"]
        s.tool_usage = d.get("tool_usage", {})
        s.start_time = time.time() - d["elapsed_at_save"]
        return s


# ----------- Orchestrator -----------

class Orchestrator:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.state_dir = Path(config["paths"]["state_dir"])
        self.output_dir = Path(config["paths"]["output_dir"])
        self.history_dir = Path(config["paths"]["history_dir"])
        self.prompt_file = config["paths"]["prompt_file"]
        for d in (self.state_dir, self.output_dir, self.history_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.log_file = Path(config["paths"]["log_file"])
        self.final_output = Path(config["paths"]["final_output"])
        self.checkpoint_path = self.state_dir / "checkpoint.pkl"

        with open("prompts/system.txt", "r", encoding="utf-8") as f:
            self.system_prompt = f.read()

        # Cache
        cache = None
        if config.get("cache", {}).get("enabled", True):
            cache = DiskCache(
                cache_dir=config["cache"]["dir"],
                ttl_seconds=config["cache"]["ttl_seconds"],
            )
        self.cache = cache

        # LLM
        llm_cfg = config["llm"]
        self.llm = LLM(
            model=llm_cfg["model"],
            embed_model=llm_cfg["embed_model"],
            host=llm_cfg["host"],
            timeout=llm_cfg["request_timeout"],
            max_tokens=llm_cfg["max_tokens"],
            keep_alive=llm_cfg.get("keep_alive", "30m"),
            cache=cache,
        )

        # Tools
        t = config["tools"]
        self.web = WebSearchTool(**t["web_search"])
        self.arxiv = ArxivSearchTool(**t["arxiv"])
        self.pdf = PdfReaderTool(**t["pdf_reader"])
        self.memory = MemoryTool(self.llm, **t["memory"])
        self.synth = SynthesizerTool(self.llm, self.memory)
        self.wiki = WikipediaTool(**t["wikipedia"])
        self.fetch = WebFetchTool(**t["web_fetch"])
        self.ss = SemanticScholarTool(**t["semantic_scholar"])
        self.hn = HackerNewsTool(**t.get("hacker_news", {}))
        self.rss = RssTool(**t.get("rss", {}))
        self.gh = GithubSearchTool(**t.get("github_search", {}))
        self.skills = SkillRegistry(self.llm, skills_dir=config["paths"]["skills_dir"])

        # Optional tracing
        self.tracing_active = maybe_setup_phoenix(config)

        # Monitor
        self.monitor_cfg = config.get("monitor", {})
        self.monitor: SystemMonitor | None = None

        self.checkpoint_every = config["agent"]["checkpoint_every_n_steps"]
        self.reflect_every = config["agent"]["reflect_every_n_steps"]
        self.max_tool_retries = config["agent"]["max_tool_retries"]

        self._shutdown = False
        self._shutdown_reason = ""
        signal.signal(signal.SIGINT, self._handle_signal)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, *_: Any) -> None:
        log.warning("Shutdown signal received — finishing current step and saving.")
        self._shutdown = True
        self._shutdown_reason = "signal"

    def _monitor_abort(self, reason: str) -> None:
        log.error("System monitor triggered abort: %s", reason)
        self._shutdown = True
        self._shutdown_reason = f"monitor:{reason}"

    # ----- logging -----

    def _log_event(self, event: dict[str, Any]) -> None:
        event["ts"] = datetime.utcnow().isoformat()
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    # ----- checkpointing -----

    def save_checkpoint(self, state: AgentState) -> None:
        with open(self.checkpoint_path, "wb") as f:
            pickle.dump(state.to_dict(), f)
        self.memory.save()
        log.info("[dim]Checkpoint saved at step %d.[/dim]", state.step)

    def load_checkpoint(self) -> AgentState | None:
        if not self.checkpoint_path.exists():
            return None
        with open(self.checkpoint_path, "rb") as f:
            return AgentState.from_dict(pickle.load(f))

    # ----- planning -----

    def plan_next(self, state: AgentState) -> dict[str, Any]:
        stats = self.memory.stats()
        recent = "\n".join(
            f"- step {a['step']}: {a['tool']} ({a.get('summary','')[:80]})"
            for a in list(state.recent_actions)[-5:]
        ) or "(none)"
        prompt = PLAN_PROMPT.format(
            goal=state.goal,
            step=state.step,
            max_steps=state.max_steps,
            elapsed_minutes=state.elapsed_seconds() / 60,
            max_minutes=state.max_seconds / 60,
            n_vectors=stats["n_vectors"],
            n_sources=stats["sources"],
            recent_actions=recent,
            notes=state.notes or "(none yet)",
        )
        try:
            action = self.llm.generate_json(
                prompt,
                system=self.system_prompt,
                temperature=self.config["llm"]["temperature_plan"],
            )
        except LLMError as e:
            log.error("Planning failed: %s", e)
            return {"thought": "planning failure", "tool": "reflect", "args": {}}
        return action

    def reflect(self, state: AgentState) -> None:
        stats = self.memory.stats()
        recent = "\n".join(
            f"- step {a['step']}: {a['tool']}" for a in list(state.recent_actions)
        )
        prompt = REFLECT_PROMPT.format(
            goal=state.goal,
            step=state.step,
            max_steps=state.max_steps,
            elapsed_minutes=state.elapsed_seconds() / 60,
            max_minutes=state.max_seconds / 60,
            n_vectors=stats["n_vectors"],
            n_sources=stats["sources"],
            sections_written=", ".join(state.sections_written) or "(none)",
            recent_actions=recent,
        )
        try:
            result = self.llm.generate_json(
                prompt,
                system=self.system_prompt,
                temperature=self.config["llm"]["temperature_plan"],
            )
            if "adjusted_notes" in result:
                state.notes = result["adjusted_notes"]
            log.info("[cyan]Reflection:[/cyan] %s", result.get("assessment", "")[:160])
            self._log_event({"type": "reflect", "step": state.step, "result": result})
        except LLMError as e:
            log.warning("Reflection failed: %s", e)

    # ----- tool dispatch -----

    def execute_tool(self, action: dict[str, Any], state: AgentState) -> str:
        tool_name = action.get("tool", "")
        args = action.get("args", {}) or {}
        log.info("[green]→ %s[/green] %s", tool_name, json.dumps(args)[:120])
        state.tool_usage[tool_name] = state.tool_usage.get(tool_name, 0) + 1

        try:
            if tool_name == "web_search":
                results = self.web.run(args.get("query", ""))
                for r in results[:5]:
                    self.memory.add(
                        f"{r['title']}\n{r['snippet']}\n{r['url']}",
                        meta={"source": r["url"], "type": "web"},
                    )
                return f"web_search returned {len(results)} results"

            if tool_name == "arxiv_search":
                results = self.arxiv.run(args.get("query", ""))
                for r in results:
                    self.memory.add(
                        f"{r['title']}\n{r['abstract']}",
                        meta={
                            "source": r["arxiv_id"],
                            "type": "arxiv_abstract",
                            "pdf_url": r["pdf_url"],
                            "title": r["title"],
                        },
                    )
                return f"arxiv_search returned {len(results)} papers"

            if tool_name == "semantic_scholar":
                results = self.ss.run(args.get("query", ""))
                for r in results:
                    body = (r.get("abstract") or r.get("tldr") or r.get("title") or "")
                    self.memory.add(
                        f"{r['title']}\n{body}",
                        meta={
                            "source": r["paper_id"] or r["title"][:30],
                            "type": "semantic_scholar",
                            "year": r.get("year"),
                            "citations": r.get("citation_count"),
                            "pdf_url": r.get("pdf_url"),
                        },
                    )
                return f"semantic_scholar returned {len(results)} papers"

            if tool_name == "wikipedia":
                r = self.wiki.run(args.get("title", ""))
                if r.get("summary"):
                    self.memory.add(
                        r["summary"],
                        meta={"source": r.get("url", r["title"]), "type": "wikipedia"},
                    )
                return f"wikipedia: {r.get('title')} ({len(r.get('summary',''))} chars)"

            if tool_name == "web_fetch":
                url = args.get("url", "")
                r = self.fetch.run(url)
                if r.get("text"):
                    # Use the shared chunker
                    from tools.chunker import chunk_text
                    for chunk in chunk_text(r["text"], chunk_size=400, overlap=40):
                        self.memory.add(chunk, meta={"source": url, "type": "web_page",
                                                     "title": r.get("title", "")})
                return f"web_fetch stored content from {url}"

            if tool_name == "hacker_news":
                results = self.hn.run(args.get("query", ""), max_results=args.get("max_results"))
                for r in results:
                    if r.get("title"):
                        self.memory.add(
                            f"{r['title']}\n{r.get('snippet','')}",
                            meta={"source": r.get("url", ""), "type": "hacker_news",
                                  "points": r.get("points", 0)},
                        )
                return f"hacker_news: {len(results)} stories for '{args.get('query','')}'"

            if tool_name == "rss":
                entries = self.rss.run(args.get("url", ""), max_entries=args.get("max_entries"))
                for e in entries:
                    if e.get("title"):
                        self.memory.add(
                            f"{e['title']}\n{e.get('summary','')}",
                            meta={"source": e.get("url", ""), "type": "rss",
                                  "feed": args.get("url", "")},
                        )
                return f"rss: stored {len(entries)} entries from {args.get('url','')}"

            if tool_name == "github_search":
                repos = self.gh.run(args.get("query", ""), max_results=args.get("max_results"))
                for r in repos:
                    self.memory.add(
                        f"{r['full_name']}: {r.get('description','')} "
                        f"(★{r.get('stars',0)}, {r.get('language','?')})",
                        meta={"source": r.get("url", ""), "type": "github_repo",
                              "stars": r.get("stars", 0)},
                    )
                return f"github_search: {len(repos)} repos for '{args.get('query','')}'"

            if tool_name == "pdf_reader":
                url = args.get("url", "")
                result = self.pdf.run(url)
                src = args.get("source_id") or url
                for chunk in result.get("chunks", []):
                    self.memory.add(chunk, meta={"source": src, "type": "pdf"})
                return f"pdf_reader stored {result.get('n_chunks', 0)} chunks from {src}"

            if tool_name == "memory_search":
                hits = self.memory.search(args.get("query", ""), top_k=args.get("top_k", 6))
                summary = "; ".join(
                    f"[{h['meta'].get('source','?')}] {h['text'][:80]}" for h in hits[:3]
                )
                return f"memory_search: {len(hits)} hits. Top: {summary}"

            if tool_name == "synthesize":
                topic = args.get("topic", state.goal)
                result = self.synth.run(topic, top_k=args.get("top_k", 8))
                section_name = args.get("section_name")
                if section_name and result.get("synthesis"):
                    self._append_section(section_name, result["synthesis"])
                    state.sections_written.append(section_name)
                return f"synthesize on '{topic}' used {result.get('n_chunks_used',0)} chunks"

            if tool_name == "use_skill":
                name = args.get("name", "")
                vars_ = args.get("vars", {}) or {}
                out = self.skills.run(name, vars_)
                return f"skill '{name}': {out[:200]}"

            if tool_name == "write_output":
                section = args.get("section_name", f"section_{len(state.sections_written)}")
                content = args.get("markdown", "")
                self._append_section(section, content)
                state.sections_written.append(section)
                return f"wrote section '{section}' ({len(content)} chars)"

            if tool_name == "reflect":
                self.reflect(state)
                return "reflection complete"

            if tool_name == "done":
                state.done = True
                return "agent signaled done"

            return f"unknown tool: {tool_name}"

        except Exception as e:
            log.exception("Tool %s failed", tool_name)
            state.tool_failures[tool_name] = state.tool_failures.get(tool_name, 0) + 1
            return f"ERROR in {tool_name}: {e}"

    def _append_section(self, name: str, content: str) -> None:
        with open(self.final_output, "a", encoding="utf-8") as f:
            f.write(f"\n\n## {name}\n\n{content}\n")

    # ----- history writing -----

    def write_history(self, state: AgentState) -> Path:
        iter_dir = self.history_dir / f"iteration_{state.iteration:03d}"
        iter_dir.mkdir(parents=True, exist_ok=True)

        # Summary
        summary_path = iter_dir / "summary.md"
        summary = (
            f"# Iteration {state.iteration}\n\n"
            f"- ts: {datetime.utcnow().isoformat()}Z\n"
            f"- steps: {state.step}/{state.max_steps}\n"
            f"- elapsed_min: {state.elapsed_seconds()/60:.1f}\n"
            f"- done: {state.done}\n"
            f"- shutdown_reason: {self._shutdown_reason or '(none)'}\n"
            f"- sections_written: {state.sections_written}\n"
            f"- tool_usage: {json.dumps(state.tool_usage)}\n"
            f"- tool_failures: {json.dumps(state.tool_failures)}\n"
        )
        if self.cache:
            summary += f"- cache_stats: {json.dumps(self.cache.stats())}\n"
        summary += f"- memory_stats: {json.dumps(self.memory.stats())}\n"
        summary += "\n## Goal\n\n" + state.goal + "\n"
        summary += "\n## Notes\n\n" + (state.notes or "(none)") + "\n"
        summary += "\n## Recent actions\n\n"
        for a in state.recent_actions:
            summary += f"- step {a['step']} `{a['tool']}` — {a.get('summary','')[:120]}\n"
        summary_path.write_text(summary, encoding="utf-8")

        # Copy outputs/final.md snapshot
        if self.final_output.exists():
            shutil.copy(self.final_output, iter_dir / "final.md")
        # Copy prompt.md snapshot
        if Path(self.prompt_file).exists():
            shutil.copy(self.prompt_file, iter_dir / "prompt.md")

        # Auto-score this iteration (deterministic, no LLM calls)
        try:
            from tools.benchmark import score_iteration, write_scorecard
            log_path = Path(self.config["paths"]["log_file"])
            # Load previous scorecard if any for delta computation
            prev_sc = None
            prior = sorted(
                [d for d in self.history_dir.glob("iteration_*") if d.is_dir() and d != iter_dir],
                key=lambda p: p.name,
            )
            if prior:
                prev_path = prior[-1] / "scorecard.json"
                if prev_path.exists():
                    try:
                        prev_sc = json.loads(prev_path.read_text(encoding="utf-8"))
                    except Exception:
                        prev_sc = None
            scorecard = score_iteration(
                iter_dir,
                agent_log_path=log_path if log_path.exists() else None,
                prev=prev_sc,
            )
            write_scorecard(iter_dir, scorecard)
            log.info(
                "[bold magenta]Scorecard:[/bold magenta] composite=%.1f  "
                "sections=%d  unique_sources=%d  tools=%d  skills=%d",
                scorecard["composite_score"],
                scorecard["n_sections"],
                scorecard["n_unique_sources"],
                scorecard["tool_diversity"],
                scorecard["skill_diversity"],
            )
        except Exception as e:
            log.warning("Scoring failed: %s", e)

        return iter_dir

    # ----- main loop -----

    def run(self, state: AgentState) -> None:
        log.info(
            "[bold]Starting agent (iteration %d).[/bold] Goal: %s",
            state.iteration,
            state.goal[:120] + ("..." if len(state.goal) > 120 else ""),
        )
        if not self.llm.health_check():
            log.error("Ollama not reachable or model not pulled. Aborting.")
            update_prompt_md(self.prompt_file, state.iteration, "failed:ollama_unreachable")
            sys.exit(1)

        # Warm up the model
        log.info("Warming up model (first call may take 10-60s)...")
        self.llm.warmup()

        # Start system monitor
        if self.monitor_cfg.get("enabled", True):
            self.monitor = SystemMonitor(
                log_path=self.config["paths"]["system_metrics_log"],
                sample_interval=self.monitor_cfg.get("sample_interval", 30.0),
                ram_abort_pct=self.monitor_cfg.get("ram_abort_pct", 95.0),
                thermal_abort_c=self.monitor_cfg.get("thermal_abort_c", 95.0),
                on_abort=self._monitor_abort,
            )
            self.monitor.start()
            # Log one sample immediately so the user sees current state
            log.info("Initial system state: %s", self.monitor.sample())

        # Initialize output file (fresh per iteration)
        if not self.final_output.exists():
            with open(self.final_output, "w", encoding="utf-8") as f:
                f.write(f"# Research Output (iteration {state.iteration})\n\n")
                f.write(f"**Goal:** {state.goal[:500]}\n\n")
                f.write(f"**Started:** {datetime.utcnow().isoformat()}Z\n")

        try:
            while not state.out_of_budget() and not state.done and not self._shutdown:
                state.step += 1
                t0 = time.time()

                action = self.plan_next(state)
                summary = self.execute_tool(action, state)

                state.recent_actions.append(
                    {
                        "step": state.step,
                        "tool": action.get("tool", ""),
                        "thought": action.get("thought", "")[:200],
                        "summary": summary,
                    }
                )
                self._log_event(
                    {
                        "type": "step",
                        "step": state.step,
                        "iteration": state.iteration,
                        "action": action,
                        "summary": summary,
                        "duration_s": time.time() - t0,
                    }
                )

                if state.step % self.reflect_every == 0:
                    self.reflect(state)
                if state.step % self.checkpoint_every == 0:
                    self.save_checkpoint(state)
        finally:
            # Stop monitor BEFORE final saves
            if self.monitor:
                self.monitor.stop()
            self.save_checkpoint(state)

            with open(self.final_output, "a", encoding="utf-8") as f:
                f.write(
                    f"\n\n---\n_Run ended at {datetime.utcnow().isoformat()}Z "
                    f"after {state.step} steps, "
                    f"{state.elapsed_seconds()/60:.1f} min. "
                    f"Reason: {self._shutdown_reason or ('done' if state.done else 'budget')}_\n"
                )

            # Write iteration history
            iter_dir = self.write_history(state)
            log.info("[bold]Iteration history written to %s[/bold]", iter_dir)

            # Update prompt.md
            status = (
                "done" if state.done
                else f"stopped:{self._shutdown_reason}" if self._shutdown_reason
                else "budget_exhausted"
            )
            update_prompt_md(self.prompt_file, state.iteration, status)

        log.info("[bold green]Run complete.[/bold green] Output: %s", self.final_output)


# ----------- CLI -----------

def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous research agent.")
    parser.add_argument("--prompt", type=str, default=None,
                        help="Path to prompt file OR inline goal. Defaults to reading prompt.md.")
    parser.add_argument("--hours", type=float, default=None, help="Max runtime in hours.")
    parser.add_argument("--steps", type=int, default=None, help="Max number of steps.")
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint.")
    parser.add_argument("--iteration", type=int, default=None,
                        help="Override iteration number (otherwise read from prompt.md).")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.hours is not None:
        config["agent"]["max_hours"] = args.hours
    if args.steps is not None:
        config["agent"]["max_steps"] = args.steps

    orch = Orchestrator(config)

    if args.resume:
        state = orch.load_checkpoint()
        if state is None:
            log.error("No checkpoint found.")
            sys.exit(1)
        log.info("Resuming from step %d", state.step)
    else:
        if args.prompt:
            if Path(args.prompt).exists():
                goal = Path(args.prompt).read_text(encoding="utf-8")
            else:
                goal = args.prompt
            iteration = args.iteration if args.iteration is not None else 1
        else:
            goal, current_iter = read_prompt_md(config["paths"]["prompt_file"])
            if not goal:
                log.error("prompt.md is empty or missing. Provide --prompt or fill prompt.md.")
                sys.exit(1)
            iteration = (args.iteration if args.iteration is not None
                         else current_iter + 1)

        state = AgentState(
            goal=goal.strip(),
            max_steps=config["agent"]["max_steps"],
            max_hours=config["agent"]["max_hours"],
            iteration=iteration,
        )

    orch.run(state)


if __name__ == "__main__":
    main()
