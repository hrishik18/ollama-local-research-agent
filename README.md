# Autonomous Local Research Agent

A lightweight autonomous research agent that runs on a **Linux laptop with 4GB RAM**. Give
it a one-shot prompt describing a research goal and let it run **unattended for 8–16 hours**,
searching the web and Arxiv, reading PDFs, building long-term memory in FAISS, and
synthesizing a final markdown deliverable.

## Features

- 🧠 **Local LLM** via [Ollama](https://ollama.com) (Qwen 2.5 1.5B default — fits in 4GB RAM)
- 🔍 **Web search** via DuckDuckGo (no API key)
- 📚 **Arxiv search** via the official `arxiv` client
- 📄 **PDF reader** via PyMuPDF (low-memory streaming extraction)
- 🧮 **FAISS vector memory** with Ollama embeddings (`nomic-embed-text`)
- 🔗 **Multi-paper synthesizer** for cohesive section writing
- ♻️ **Checkpoint & resume** — crashes don't lose progress
- 🛑 **Graceful shutdown** on SIGINT / SIGTERM
- 🎛️ **Configurable** budgets (steps, hours), tools, and model via `config.yaml`

## Architecture

```
main.py (ReAct orchestrator)
   ├── llm.py            Ollama wrapper (generation + embeddings)
   ├── tools/
   │   ├── web_search.py     DuckDuckGo
   │   ├── arxiv_search.py   Arxiv API
   │   ├── pdf_reader.py     PyMuPDF download + chunk
   │   ├── memory.py         FAISS index + metadata
   │   └── synthesizer.py    Cross-source synthesis
   ├── prompts/
   │   ├── system.txt        Agent system prompt
   │   ├── templates.py      Plan & reflection templates
   │   └── example_goal.txt  Example one-shot goal
   ├── state/                Runtime state (FAISS, PDFs, checkpoint)
   └── outputs/              Final deliverables + log
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
git clone <this-repo>
cd ollama_local_setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
# Make sure Ollama is running
ollama serve &

# Run with a goal file
python main.py --prompt prompts/example_goal.txt --hours 12

# Or inline
python main.py --prompt "Research the latest in autonomous agents..." --hours 8

# Resume from crash
python main.py --resume
```

## Outputs

- `outputs/final.md` — The final synthesized deliverable
- `outputs/agent_log.jsonl` — Step-by-step structured log
- `state/faiss.index` + `state/metadata.json` — Persistent memory
- `state/checkpoint.pkl` — Crash-recovery state

## RAM Budget (4GB Target)

| Component               | RAM     |
|-------------------------|---------|
| Linux OS                | ~500MB  |
| Ollama + Qwen 1.5B      | ~1.5GB  |
| Ollama nomic-embed      | ~300MB (shared process) |
| Python + FAISS index    | ~300MB  |
| PDF processing (peak)   | ~100MB  |
| **Total**               | ~2.7GB  |
| **Headroom**            | ~1.3GB  |

If you have more RAM, edit `config.yaml` and switch to `qwen2.5:3b` for better quality.

## Configuration

Edit `config.yaml` to tune:
- LLM model and temperature
- Step / time budgets
- Tool-specific limits (max results, chunk size, rate limits)
- Paths

## Safety / Reliability

- Checkpoint every 10 steps (configurable)
- Periodic self-reflection every 20 steps
- Per-tool failure tracking; failing tools don't crash the loop
- Output document is appended-to incrementally — partial progress is preserved

## Running via Microsoft `agency` Copilot CLI (autopilot)

If you want to drive long-horizon autonomous runs through the `agency` CLI instead of
the local Ollama loop in `main.py`, use the launcher scripts:

```bash
# Linux / WSL
./scripts/run_autopilot.sh prompts/example_goal.txt 300

# Windows PowerShell
.\scripts\run_autopilot.ps1 -PromptFile prompts\example_goal.txt -MaxContinues 300
```

Under the hood this runs:

```
agency copilot --autopilot --max-autopilot-continues <N> --model <M> -p "<prompt>"
```

Key flags:
- `--autopilot` — no interactive prompts between turns
- `--max-autopilot-continues` — bump high (200-500) for 8-16h sessions; default is 5
- `--continue` — resume the most recent session if it died
- `--available-tools` / `--deny-tool` — gate tools to avoid permission prompts blocking the loop

## License

MIT
