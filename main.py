"""Autonomous research agent — orchestrator / ReAct loop.

Usage:
    python main.py --prompt prompts/example_goal.txt --hours 12
    python main.py --resume
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
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
    MemoryTool,
    PdfReaderTool,
    SynthesizerTool,
    WebSearchTool,
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


# ----------- Agent state -----------

class AgentState:
    def __init__(self, goal: str, max_steps: int, max_hours: float) -> None:
        self.goal = goal
        self.max_steps = max_steps
        self.max_seconds = max_hours * 3600
        self.start_time = time.time()
        self.step = 0
        self.notes = ""
        self.recent_actions: deque[dict[str, Any]] = deque(maxlen=10)
        self.sections_written: list[str] = []
        self.tool_failures: dict[str, int] = {}
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
            "max_steps": self.max_steps,
            "max_seconds": self.max_seconds,
            "step": self.step,
            "notes": self.notes,
            "recent_actions": list(self.recent_actions),
            "sections_written": self.sections_written,
            "tool_failures": self.tool_failures,
            "elapsed_at_save": self.elapsed_seconds(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AgentState":
        s = cls(d["goal"], d["max_steps"], d["max_seconds"] / 3600)
        s.step = d["step"]
        s.notes = d["notes"]
        s.recent_actions = deque(d["recent_actions"], maxlen=10)
        s.sections_written = d["sections_written"]
        s.tool_failures = d["tool_failures"]
        s.start_time = time.time() - d["elapsed_at_save"]
        return s


# ----------- Orchestrator -----------

class Orchestrator:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.state_dir = Path(config["paths"]["state_dir"])
        self.output_dir = Path(config["paths"]["output_dir"])
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.log_file = Path(config["paths"]["log_file"])
        self.final_output = Path(config["paths"]["final_output"])
        self.checkpoint_path = self.state_dir / "checkpoint.pkl"

        # System prompt
        with open("prompts/system.txt", "r", encoding="utf-8") as f:
            self.system_prompt = f.read()

        # LLM
        llm_cfg = config["llm"]
        self.llm = LLM(
            model=llm_cfg["model"],
            embed_model=llm_cfg["embed_model"],
            host=llm_cfg["host"],
            timeout=llm_cfg["request_timeout"],
            max_tokens=llm_cfg["max_tokens"],
        )

        # Tools
        t = config["tools"]
        self.web = WebSearchTool(**t["web_search"])
        self.arxiv = ArxivSearchTool(**t["arxiv"])
        self.pdf = PdfReaderTool(**t["pdf_reader"])
        self.memory = MemoryTool(self.llm, **t["memory"])
        self.synth = SynthesizerTool(self.llm, self.memory)

        self.checkpoint_every = config["agent"]["checkpoint_every_n_steps"]
        self.reflect_every = config["agent"]["reflect_every_n_steps"]
        self.max_tool_retries = config["agent"]["max_tool_retries"]

        self._shutdown = False
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, *_: Any) -> None:
        log.warning("Shutdown signal received — finishing current step and saving.")
        self._shutdown = True

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
            log.info("[cyan]Reflection:[/cyan] %s", result.get("assessment", ""))
            self._log_event({"type": "reflect", "step": state.step, "result": result})
        except LLMError as e:
            log.warning("Reflection failed: %s", e)

    # ----- tool dispatch -----

    def execute_tool(self, action: dict[str, Any], state: AgentState) -> str:
        tool_name = action.get("tool", "")
        args = action.get("args", {}) or {}
        log.info("[green]→ %s[/green] %s", tool_name, json.dumps(args)[:120])

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
                # Optionally append synthesis to output
                section_name = args.get("section_name")
                if section_name and result.get("synthesis"):
                    self._append_section(section_name, result["synthesis"])
                    state.sections_written.append(section_name)
                return f"synthesize on '{topic}' used {result.get('n_chunks_used',0)} chunks"

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

    # ----- main loop -----

    def run(self, state: AgentState) -> None:
        log.info(
            "[bold]Starting agent.[/bold] Goal: %s",
            state.goal[:120] + ("..." if len(state.goal) > 120 else ""),
        )
        if not self.llm.health_check():
            log.error("Ollama not reachable or model not pulled. Aborting.")
            sys.exit(1)

        # Initialize output file
        if not self.final_output.exists():
            with open(self.final_output, "w", encoding="utf-8") as f:
                f.write(f"# Research Output\n\n**Goal:** {state.goal}\n\n")
                f.write(f"**Started:** {datetime.utcnow().isoformat()}Z\n")

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
                    "action": action,
                    "summary": summary,
                    "duration_s": time.time() - t0,
                }
            )

            if state.step % self.reflect_every == 0:
                self.reflect(state)
            if state.step % self.checkpoint_every == 0:
                self.save_checkpoint(state)

        # Final save
        self.save_checkpoint(state)
        with open(self.final_output, "a", encoding="utf-8") as f:
            f.write(f"\n\n---\n_Run ended at {datetime.utcnow().isoformat()}Z "
                    f"after {state.step} steps, "
                    f"{state.elapsed_seconds()/60:.1f} min._\n")
        log.info("[bold green]Run complete.[/bold green] Output: %s", self.final_output)


# ----------- CLI -----------

def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous research agent.")
    parser.add_argument("--prompt", type=str, help="Path to prompt file OR inline goal text.")
    parser.add_argument("--hours", type=float, default=None, help="Max runtime in hours.")
    parser.add_argument("--steps", type=int, default=None, help="Max number of steps.")
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint.")
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
        if not args.prompt:
            log.error("--prompt is required (file path or inline text).")
            sys.exit(1)
        if Path(args.prompt).exists():
            goal = Path(args.prompt).read_text(encoding="utf-8")
        else:
            goal = args.prompt
        state = AgentState(
            goal=goal.strip(),
            max_steps=config["agent"]["max_steps"],
            max_hours=config["agent"]["max_hours"],
        )

    orch.run(state)


if __name__ == "__main__":
    main()
