"""Prompt templates for the agent loop."""

from __future__ import annotations


PLAN_PROMPT = """GOAL:
{goal}

CURRENT STEP: {step} of {max_steps}
ELAPSED: {elapsed_minutes:.0f} min of {max_minutes:.0f} min
MEMORY: {n_vectors} chunks stored from {n_sources} sources
RECENT ACTIONS (last 5):
{recent_actions}

NOTES SO FAR:
{notes}

Decide the next action. Return a JSON object with keys: thought, tool, args.
Available tools: web_search, arxiv_search, pdf_reader, memory_search, synthesize,
write_output, reflect, done.
"""


REFLECT_PROMPT = """GOAL:
{goal}

PROGRESS:
- Steps used: {step}/{max_steps}
- Time used: {elapsed_minutes:.0f}/{max_minutes:.0f} min
- Chunks in memory: {n_vectors} from {n_sources} sources
- Output sections written: {sections_written}

RECENT ACTIONS:
{recent_actions}

Reflect honestly:
1. Are we on track to meet the goal in the remaining budget?
2. What sub-topics still need coverage?
3. What should we stop doing? What should we do more of?
4. Is it time to start synthesizing and writing?

Return JSON with keys: assessment (string), next_focus (list of strings),
should_start_writing (bool), adjusted_notes (string to replace running notes).
"""
