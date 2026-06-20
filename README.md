# Autonomous Local Research Agent

A lightweight autonomous research agent that runs on a **Linux laptop with 4GB RAM**.
Edit `prompt.md`, start the agent, and let it run **unattended for 8-16 hours** searching
Arxiv, Semantic Scholar, the web, Wikipedia and PDFs, building hybrid RAG memory in
FAISS+BM25, and synthesizing a final markdown deliverable - with per-iteration history
and system monitoring (RAM + thermals).

## Features

- **Local LLM** via [Ollama](https://ollama.com) (Qwen 2.5 1.5B default - fits in 4GB)
- **Thermal & RAM monitor** - auto-abort if CPU > 95C or RAM > 95%
- **Multi-iteration mode** - `iterate.py` runs N iterations, evolving `prompt.md` each time
- **`history/` folder** - every iteration archived with summary + prompt + output
- **Hybrid RAG retrieval** - FAISS (dense vectors) + BM25 (sparse keywords) re-ranked
- **Smart chunking** - paragraph + sentence boundaries, not naive sliding windows
- **11 tools**: web_search, arxiv, semantic_scholar, wikipedia, web_fetch, hacker_news, rss, github_search, pdf_reader, memory, synthesizer (+ optional `browser` via Playwright for JS-heavy pages)
- **10 skills** in `skills/*.md` - reusable prompt patterns (editable, no code)
- **Benchmark scoring** - every iteration auto-scored on 12+ metrics (composite 0-100) → `history/iteration_NNN/scorecard.json`. Tells you whether each iteration was actually better than the previous.
- **Traceability dashboard** - `python dashboard/app.py` opens a Flask UI with composite-score trends, per-iteration scorecards, tool/skill × iteration heatmaps, drill-down step timelines, and live RAM/temp charts
- **Optional Phoenix tracing** - opt-in OpenTelemetry export to a local [Arize Phoenix](https://github.com/Arize-ai/phoenix) instance for prompt-level observability
- **Speed**: Ollama `keep_alive` keeps model warm; disk cache deduplicates LLM/embedding calls
- **Checkpoint & resume** - crashes don't lose progress
- **Graceful shutdown** on SIGINT / SIGTERM / monitor abort
- **Prompt compression (optional)** - [headroom-ai](https://github.com/chopratejas/headroom) cuts input tokens 50-90% on tool-output-heavy turns; big speedup on slow CPU inference
- **Tested** - `pytest tests/` (37 tests, no Ollama required)

## Architecture

```
prompt.md (editable goal + iteration counter + learnings)
        |
        v
main.py (ReAct orchestrator)
   |-- llm.py            Ollama + cache + keep_alive
   |-- tools/
   |   |-- web_search.py        DuckDuckGo
   |   |-- arxiv_search.py      Arxiv API
   |   |-- semantic_scholar.py  Semantic Scholar (citations, TLDR, PDF URLs)
   |   |-- wikipedia.py         Wikipedia summaries
   |   |-- web_fetch.py         Generic web page extractor
   |   |-- browser.py           Optional Playwright headless browser (JS pages)
   |   |-- pdf_reader.py        PyMuPDF download + chunk
   |   |-- chunker.py           Paragraph/sentence-aware chunker
   |   |-- memory.py            FAISS + BM25 hybrid retrieval
   |   |-- synthesizer.py       Multi-source synthesis
   |   |-- skills.py            Skill registry / runner
   |   |-- cache.py             Disk-backed response cache
   |   |-- compressor.py        Optional headroom-ai prompt compression
   |   |-- benchmark.py         Per-iteration deterministic scorecard
   |   |-- notifier.py          ntfy.sh / notify-send / console alerts
   |   `-- system_monitor.py    RAM + thermal sampler + auto-abort
   |-- skills/                  Reusable prompt patterns (.md)
   |-- prompts/system.txt       Agent system prompt
   |-- history/                 Per-iteration archive (auto-written)
   |-- state/                   FAISS index, PDFs, checkpoint
   |-- cache/                   LLM/embedding response cache
   `-- outputs/                 final.md + JSONL logs
       |
iterate.py - runs main.py N times, evolves prompt.md between runs via the
             improve_prompt skill
```

See [`plan.md`](plan.md) for the full design document.

## Setup (Linux)

```bash
# 1. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 2. Pull models
ollama pull qwen2.5:1.5b
ollama pull nomic-embed-text

# 3. Clone & install
git clone https://github.com/hsancheti_microsoft/ollama-local-research-agent.git
cd ollama-local-research-agent
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.lock.txt   # pinned, reproducible (134 packages)
#   or: pip install -r requirements.txt # loose >= constraints, latest versions

# 4. Edit the goal
$EDITOR prompt.md

# 5. Run the smoke tests (no Ollama needed)
pytest tests/ -v

# 6. (optional) Launch the traceability dashboard in another terminal
chmod +x dashboard/run.sh
./dashboard/run.sh                       # http://localhost:5050
#   or: python scripts/seed_demo_history.py   # if you have no iterations yet
```

**Faster bootstrap on a fresh Linux/WSL box** — does everything in step 1-5 above
in one idempotent script (apt deps + Ollama + model pull + venv + smoke tests):

```bash
bash scripts/wsl_setup.sh
```

**No Linux laptop handy?** Spin up a Standard_B2s Ubuntu VM (4 GB RAM, mimics
the target) that runs the same bootstrap remotely:

```bash
./scripts/azure_vm_setup.sh             # provision + bootstrap
./scripts/azure_vm_setup.sh --destroy   # tear down
```

## Usage

### Single long run
```bash
ollama serve &
# Reads goal from prompt.md and runs one iteration
python main.py --hours 12
```

### Multi-iteration (recommended for unattended overnight)
```bash
# 3 iterations of 4 hours each, evolving prompt.md between them
python iterate.py --n 3 --hours-per-iter 4
```

Between iterations, the agent invokes the `improve_prompt` skill to look at what
happened, propose edits to the goal prompt, and append learnings. Each iteration is
archived under `history/iteration_NNN/` with:
- `summary.md` - step count, tool usage, failures, cache stats, system metrics
- `prompt.md` - snapshot of the goal at that point
- `final.md` - output produced this iteration

### Inline / scripted goal (bypasses prompt.md)
```bash
python main.py --prompt "Research the latest in autonomous agents..." --hours 8
```

### Resume after crash
```bash
python main.py --resume
```

## Outputs

- `outputs/final.md` - Final synthesized deliverable
- `outputs/agent_log.jsonl` - Step-by-step JSONL log
- `outputs/system_metrics.jsonl` - RAM / CPU / thermal samples (every 30s)
- `history/iteration_NNN/` - Per-iteration archive
- `state/faiss.index` + `state/metadata.json` - Hybrid memory (FAISS + BM25)
- `state/checkpoint.pkl` - Crash-recovery state
- `cache/` - Disk-backed LLM/embedding cache

## Editing prompt.md

`prompt.md` is the user-editable mission control:
- `## GOAL` - what to research (you edit this)
- `## LEARNINGS` - agent appends concise lessons after each iteration
- `## ITERATION` - counter + last-run status (agent-maintained)

You can edit GOAL at any time between iterations. Run `python iterate.py` and the
agent will pick up the latest version.

## Skills

Skills are reusable prompt patterns in `skills/*.md`. Add your own by dropping a new
`.md` file with `USE WHEN:` and `## TEMPLATE` sections. Variables use `{name}` syntax.
Current skills:
- `extract_paper_findings` - structured extraction from a paper
- `compare_approaches` - comparison table across sources
- `evaluate_progress` - self-assessment at reflection checkpoints
- `improve_prompt` - auto-evolve the goal between iterations
- `summarize_chunks` - tighten retrieved chunks into bullets

## RAM Budget (4GB Target)

| Component               | RAM     |
|-------------------------|---------|
| Linux OS                | ~500MB  |
| Ollama + Qwen 1.5B      | ~1.5GB  |
| Ollama nomic-embed      | ~300MB  |
| Python + FAISS + BM25   | ~350MB  |
| PDF processing (peak)   | ~100MB  |
| **Total**               | ~2.75GB |
| **Headroom**            | ~1.25GB |

The `SystemMonitor` will abort the run if RAM exceeds 95% or any thermal zone exceeds
95 C. Thresholds are configurable in `config.yaml` under `monitor:`.

## Configuration

Everything lives in `config.yaml`:
- `llm.model` - switch to `qwen2.5:3b` if you have more RAM
- `llm.keep_alive` - how long Ollama keeps the model warm
- `cache.enabled` - disable cache if you want fresh runs every time
- `monitor.ram_abort_pct` / `monitor.thermal_abort_c` - safety thresholds
- `tools.memory.hybrid_alpha` - vector/BM25 mix (1.0 = vector only)
- `agent.checkpoint_every_n_steps` / `reflect_every_n_steps`

## Running via `agency` Copilot CLI

If you want to drive this through Microsoft's `agency copilot --autopilot` (cloud LLM)
instead of the local Ollama loop, use the launcher scripts:

```bash
./scripts/run_autopilot.sh prompts/example_goal.txt 300   # Linux
.\scripts\run_autopilot.ps1 -PromptFile prompts\example_goal.txt -MaxContinues 300  # Windows
```

## Dashboard

A Flask traceability dashboard that answers **"is iteration N better than N-1?"** with numbers:

```bash
python dashboard/app.py
# then open http://localhost:5050
```

No real iterations yet? Seed three demo iterations to see what it looks like:

```bash
python scripts/seed_demo_history.py --force
```

What it shows:

- **Composite score** (0–100) per iteration, weighted across 9 deterministic metrics
- **Iteration scorecards** — table with score, Δ vs previous, sections, unique sources, citations, tool/skill diversity, success ratio, steps, minutes, status
- **Trend charts** — output growth (chars, citations, sections) and operational quality (tool diversity, skill diversity, success ratio) over time
- **Tool × iteration heatmap** — which tool was called in which run, color-intensity by call count
- **Skill × iteration heatmap** — same for skills
- **Drill-down modal** — click any iteration row to see its full step-by-step timeline (every tool call, every skill invocation, every reflection — with thought, result snippet, and duration)
- **Live RAM / CPU / thermal** time series (refreshes every 30 s)
- **Skills catalogue** and **experiment notes**
- **Latest final.md** rendered Markdown

The agent now auto-writes `history/iteration_NNN/scorecard.json` at the end of every run (via `tools/benchmark.py`). To re-score existing runs after a code change:

```bash
python scripts/benchmark_iterations.py --print
```

## Prompt compression (optional, recommended on 4 GB CPU)

Qwen 1.5B on a 4 GB CPU laptop is wall-time-bound by prompt tokens — every
input token is a forward pass before the first output token streams. On
tool-output-heavy turns (search results, PDF chunks, agent_log digests),
50-90% of those tokens are noise.

[Headroom](https://github.com/chopratejas/headroom) compresses prompts
locally before they reach Ollama, with zero external API calls. We integrate
it as an optional, graceful-degrading layer in `LLM.generate`:

```bash
pip install "headroom-ai[all]"
# config.yaml:
#   compression:
#     enabled: true
#     min_input_chars: 2000
#     model_hint: "gpt-4o"      # tokenizer for counting (not for inference)
python main.py
```

- JSON-mode calls are skipped (compression can break strict JSON).
- Short prompts (< `min_input_chars`) are skipped (overhead > savings).
- If `headroom-ai` isn't installed, the compressor silently no-ops.
- Per-call savings are written to `outputs/compression_log.jsonl` and shown
  in the dashboard's "🗜️ Prompt compression" tile.

## Browser automation (optional, Playwright)

`web_fetch` uses requests+BeautifulSoup — fast, but blind to JavaScript.
Modern SPA docs (React/Next/Vercel), dynamic dashboards, lazy-loaded pages,
and Cloudflare-protected sites return empty bodies. The `browser` tool spins
up a headless Chromium per call (Playwright) and returns the real rendered
text — what a human in a browser actually sees.

```bash
pip install playwright
playwright install chromium     # ~300 MB browser binary
# config.yaml:
#   tools:
#     browser:
#       enabled: true
python main.py
```

The agent reaches for `browser(url=...)` only when `web_fetch` returned
empty/JS-shell content. Each call is ~150 MB peak RAM and ~5-8 s overhead
(images/fonts/CSS are blocked to keep it fast). The browser closes after
every call — no long-lived context on the 4 GB box. Tune everything under
`tools.browser.*` in `config.yaml`: `engine` (chromium/firefox/webkit),
`nav_timeout_ms`, `wait_after_load_ms`, `block_resources`, `headless`.

The `browser_automation.md` skill teaches the LLM *when* to reach for it
vs. `web_fetch`, and what JSON to return after a successful render.

If `playwright` isn't installed, the tool returns a clear error string the
agent can fall back from — it never crashes the overnight run.

## Phoenix tracing (optional)

To inspect every LLM prompt/response, latency, and token count in a web UI:

```bash
pip install arize-phoenix-otel openinference-instrumentation-ollama
phoenix serve &
# In config.yaml: tracing.enabled = true
python main.py
# open http://localhost:6006
```

If disabled or the packages aren't installed, this is a no-op.

## Testing

```bash
pytest tests/ -v
```

10 smoke tests verify the chunker, cache, prompt.md parser, skills loader, system
monitor, and config - all without needing Ollama. `tests/test_v03.py`,
`test_v04.py`, `test_v05.py`, and `test_v06.py` add skills, benchmark-scoring,
dashboard, headroom-compression, and browser-tool tests.
**44 tests total, all pass without Ollama or Playwright installed.**

## License

MIT
