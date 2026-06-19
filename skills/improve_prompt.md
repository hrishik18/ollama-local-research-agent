# improve_prompt

USE WHEN: Between iterations, to evolve the goal prompt based on what was learned.

## TEMPLATE

The current goal prompt (prompt.md) is:

---
{current_prompt}
---

The most recent run produced this summary of actions:
{last_run_summary}

Final output produced (first 2000 chars):
{output_preview}

Propose at most 5 concise edits to improve the next iteration. Each edit should be
either:
- a CLARIFICATION (something the agent misinterpreted)
- a CONSTRAINT (something to add/remove from scope)
- a HINT (a sub-topic or search query the agent should try)

Return JSON with:
- "edits": list of strings (each one a single edit, prefixed CLARIFY:/CONSTRAINT:/HINT:)
- "learnings_to_append": string — short bullets to append to LEARNINGS section
- "rationale": 1-2 sentence justification

Return ONLY valid JSON.
