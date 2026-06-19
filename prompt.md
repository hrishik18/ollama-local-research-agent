# Research Goal (editable)

> **This file is read at every iteration.** Edit the GOAL section to direct the agent.
> The agent will append learnings to the LEARNINGS section and bump the iteration counter
> at the bottom after each run. Past versions are archived under `history/`.

## GOAL

Produce a literature survey on **"Retrieval-Augmented Generation (RAG) for
domain-specific applications"** covering papers from 2023-2025.

### Scope
- Search Arxiv for relevant papers (15–40 papers)
- Read & extract key findings from the highest-signal ones
- Organize by sub-topics: medical RAG, legal RAG, code RAG, scientific RAG
- Include a comparison of approaches and a future-directions section

### Output
A markdown document at `outputs/final.md` with:
- Executive summary (~500 words)
- Per-topic sections with citations to arxiv_id
- Comparison of approaches
- Future directions
- Bibliography

### Constraints
- Cite every claim with the source identifier (arxiv_id or URL)
- Prefer recent papers (2024-2025) when quality is comparable
- Skip non-English papers
- Time budget: 12 hours (configurable via CLI)
- Step budget: 500 steps (configurable via CLI)

---

## LEARNINGS (agent-managed — do not delete the heading)

<!-- The agent appends concise lessons from each iteration below this line. -->

---

## ITERATION

current_iteration: 0
last_run_ts: never
last_run_status: not_started
