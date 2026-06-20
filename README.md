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
- **11 tools**: web_search, arxiv, semantic_scholar, wikipedia, web_fetch, hacker_news, rss, github_search, pdf_reader, memory, synthesizer
- **8 skills** in `skills/*.md` - reusable prompt patterns (editable, no code)
- **Dashboard** - `python dashboard/app.py` opens a Flask web UI showing iterations, tool usage, RAM/temperature charts, and rendered outputs
- **Optional Phoenix tracing** - opt-in OpenTelemetry export to a local [Arize Phoenix](https://github.com/Arize-ai/phoenix) instance for prompt-level observability
- **Speed**: Ollama `keep_alive` keeps model warm; disk cache deduplicates LLM/embedding calls
- **Checkpoint & resume** - crashes don't lose progress
- **Graceful shutdown** on SIGINT / SIGTERM / monitor abort
- **Tested** - `pytest tests/` (21 smoke tests, no Ollama required)

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
   |   |-- pdf_reader.py        PyMuPDF download + chunk
   |   |-- chunker.py           Paragraph/sentence-aware chunker
   |   |-- memory.py            FAISS + BM25 hybrid retrieval
   |   |-- synthesizer.py       Multi-source synthesis
   |   |-- skills.py            Skill registry / runner
   |   |-- cache.py             Disk-backed response cache
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
pip install -r requirements.txt

# 4. Edit the goal
$EDITOR prompt.md

# 5. Run the smoke tests (no Ollama needed)
pytest tests/ -v
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

A lightweight Flask web UI to inspect runs visually:

```bash
python dashboard/app.py
# then open http://localhost:5050
```

Shows: iterations table, tool-usage bar chart, RAM/CPU/thermal time series,
skills catalogue, experiment notes (e.g. `history/experiment_*.md`), and the
rendered Markdown of the latest `outputs/final.md`. Auto-refreshes system
metrics every 30 seconds.

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
monitor, and config - all without needing Ollama.

## License

MIT
