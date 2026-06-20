# Dashboard

A lightweight Flask web UI that visualizes the agent's history and runtime metrics.

## Run

```bash
pip install flask
python dashboard/app.py
# open http://localhost:5050
```

## What it shows

- **Iterations** — every run from `history/iteration_*/` with status, steps, duration, sections written
- **Experiments** — free-form `history/*.md` files (e.g., `experiment_001_darkforge_phoenix.md`)
- **Tool usage** — bar chart of which tools were used in the latest iteration
- **RAM / CPU** — live system metrics from `outputs/system_metrics.jsonl` (auto-refreshes every 30s)
- **Thermals** — temperature line chart with abort threshold marker
- **Skills** — table of all loaded skills + their `USE WHEN` description
- **Final output** — rendered Markdown preview of the latest `outputs/final.md`

## Dependencies

- `flask` (only addition beyond the main agent's requirements)
- Chart.js + Marked.js are loaded from CDN at runtime — no build step

## Why a single file?

Keeps the 4GB-RAM target happy: no Node, no bundler, no Docker. Just `python dashboard/app.py`.
