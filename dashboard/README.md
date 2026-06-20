# Dashboard

A traceability Flask web UI: per-iteration scorecards (composite 0-100), tool/skill heatmaps,
trend lines, drill-down step timelines, and live RAM/temp charts.

## Linux / macOS quick start

```bash
# from the repo root
pip install -r requirements.txt          # one-time
chmod +x dashboard/run.sh                # one-time
./dashboard/run.sh                       # then open http://localhost:5050
```

Or directly:

```bash
python dashboard/app.py                  # default http://127.0.0.1:5050
python dashboard/app.py --port 8080      # custom port
python dashboard/app.py --host 0.0.0.0   # expose on your LAN (other devices on Wi-Fi)
DASHBOARD_PORT=8080 python dashboard/app.py
```

`config.yaml` `dashboard.host` / `dashboard.port` are picked up automatically
(CLI flags > env vars > config.yaml).

## No iterations yet?

The dashboard will be empty before the agent has produced any iterations. Seed
3 synthetic iterations to preview the UI:

```bash
python scripts/seed_demo_history.py --force
```

Or just run the agent once:

```bash
python main.py            # produces history/iteration_001/, scorecard.json, etc.
```

## What it shows

- **Composite score** (0-100) per iteration with Δ vs previous
- **Iteration scorecards** — sortable table with sections, sources, citations, tool/skill diversity, success ratio, steps, minutes, status
- **Trend charts** — output growth and operational quality over time
- **Tool × iteration heatmap** and **Skill × iteration heatmap**
- **Drill-down modal** (click any row) — every step's tool, skill, thought, result, and duration
- **Live RAM / CPU / thermal** time series
- **Skills catalogue** and **experiment notes**
- **Latest final.md** rendered Markdown

## Re-score past iterations after a code change

```bash
python scripts/benchmark_iterations.py --print
```

## Dependencies

- `flask` (only addition beyond the agent's core deps)
- Chart.js + Marked.js are loaded from CDN at runtime, so an active internet
  connection is needed the first time you load the page in a given browser
  (everything is cached after that). For fully offline laptops, vendor those
  two files locally and replace the two `<script src="https://cdn...">` tags
  in `dashboard/app.py`.

## Why a single file?

Keeps the 4 GB RAM target happy: no Node, no bundler, no Docker. Just
`python dashboard/app.py`.
