# Skills — Reusable Prompt Patterns

Skills are short, focused prompt templates the agent can invoke to perform a specific
sub-task with high reliability. Each skill is a markdown file with:

- A title
- A description of when to use it
- A `## TEMPLATE` section containing the prompt with `{placeholder}` variables

The agent loads all `.md` files in this folder at startup and exposes them as the
`use_skill` tool: `use_skill(name="extract_paper_findings", vars={...})`.

## Why skills?

The local Qwen 1.5B model is small and easily distracted. Wrapping recurring sub-tasks
in tight, focused prompts dramatically improves output quality on a slow CPU. Skills also
make the agent's behavior easier to inspect and edit — you can tune a skill without
touching Python.

## Current skills

- `extract_paper_findings.md` — Pull structured findings from a paper abstract or PDF chunk
- `compare_approaches.md` — Build a comparison table across retrieved chunks
- `evaluate_progress.md` — Self-evaluate whether the goal is being met
- `improve_prompt.md` — Look at last iteration and propose an improved goal prompt
- `summarize_chunks.md` — Condense N retrieved chunks into a tight bullet list
