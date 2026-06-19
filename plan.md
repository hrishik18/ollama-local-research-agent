# Autonomous Research Agent — Project Plan

## Vision
A lightweight, autonomous AI research agent that runs on a **Linux laptop with 4GB RAM**. You give it a one-shot prompt (e.g., "Build me a comprehensive survey on X") and let it run unattended for **8–16 hours**, researching, reading papers, synthesizing information, and producing a final output.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│                   main.py                        │
│              (Orchestrator / Agent Loop)         │
│                                                  │
│  ┌───────────┐  ┌──────────┐  ┌─────────────┐  │
│  │ Plan Step │→ │ Execute  │→ │ Reflect &   │  │
│  │ (Think)   │  │ (Act)    │  │ Store       │  │
│  └───────────┘  └──────────┘  └─────────────┘  │
│        ↕              ↕              ↕           │
│  ┌─────────────────────────────────────────┐    │
│  │           Tool Router                    │    │
│  └─────────────────────────────────────────┘    │
└──────────┬──────────┬──────────┬──────────┬─────┘
           │          │          │          │
     ┌─────▼───┐ ┌───▼────┐ ┌──▼───┐ ┌───▼──────┐
     │ Web     │ │ Arxiv  │ │ PDF  │ │ Memory   │
     │ Search  │ │ Search │ │Reader│ │ (FAISS)  │
     └─────────┘ └────────┘ └──────┘ └──────────┘
```

---

## File Structure

```
ollama_research_agent/
├── main.py              # Orchestrator — ReAct agent loop
├── llm.py              # Qwen model interface via Ollama
├── tools/
│   ├── __init__.py
│   ├── web_search.py   # DuckDuckGo search (no API key needed)
│   ├── arxiv_search.py # Arxiv API client
│   ├── pdf_reader.py   # PDF download + text extraction
│   ├── memory.py       # FAISS vector store for long-term memory
│   └── synthesizer.py  # Multi-paper synthesis tool
├── prompts/
│   ├── system.txt      # System prompt for the agent
│   └── templates.py    # Prompt templates for each phase
├── state/
│   └── (runtime state, checkpoints, FAISS index)
├── outputs/
│   └── (final deliverables)
├── requirements.txt
├── config.yaml         # Model settings, timeouts, limits
└── README.md
```

---

## Component Details

### 1. `llm.py` — Local Qwen Model Interface

- **Model**: `qwen2.5:1.5b` or `qwen2.5:3b` (fits in 4GB RAM with Ollama)
- **Backend**: Ollama (simple HTTP API on localhost:11434)
- **Features**:
  - Structured output parsing (JSON mode)
  - Token counting / context window management
  - Retry logic with exponential backoff
  - Temperature control per phase (low for planning, higher for synthesis)
  - Streaming support for long generations

```python
# Key interface
class LLM:
    def generate(self, prompt: str, system: str = None, json_mode: bool = False) -> str
    def generate_stream(self, prompt: str) -> Generator[str, None, None]
```

### 2. `main.py` — Orchestrator (ReAct Agent Loop)

- **Pattern**: ReAct (Reason + Act) with periodic self-reflection
- **Loop**:
  1. **Plan**: Given the goal + current memory, decide next action
  2. **Act**: Call the chosen tool
  3. **Observe**: Process tool output
  4. **Reflect**: Every N steps, summarize progress & adjust plan
  5. **Checkpoint**: Save state to disk (crash recovery)
  6. **Terminate**: When goal is met or time/step budget exhausted

- **Autonomy features**:
  - Step budget (e.g., max 500 steps over 16 hours)
  - Time budget with graceful shutdown
  - Auto-recovery from crashes (checkpoint/resume)
  - Error handling: retry failed tools, skip after 3 failures
  - Progress logging to `outputs/log.md`

### 3. Tools

#### 3a. Web Search (`tools/web_search.py`)
- **Library**: `duckduckgo-search` (no API key, free)
- **Function**: Search the web, return top N results with titles + snippets + URLs
- **Rate limiting**: 1 request per 3 seconds to avoid blocks
- **RAM**: Negligible

#### 3b. Arxiv Search (`tools/arxiv_search.py`)
- **Library**: `arxiv` (official Python client)
- **Function**: Search papers by query, return titles, abstracts, PDF URLs, dates
- **Features**: Sort by relevance/date, filter by category
- **RAM**: Negligible

#### 3c. PDF Reader (`tools/pdf_reader.py`)
- **Library**: `pymupdf` (fitz) — fast, low memory
- **Function**: Download PDF → extract text → chunk into sections
- **Strategy**: Process one PDF at a time, extract text, discard PDF from memory
- **Chunking**: ~500 token chunks with overlap for FAISS ingestion
- **RAM**: ~50-100MB peak per PDF (released after processing)

#### 3d. Memory / FAISS (`tools/memory.py`)
- **Library**: `faiss-cpu` + `sentence-transformers` (or use Ollama embeddings)
- **Embedding model**: `all-MiniLM-L6-v2` (~80MB) OR Ollama's built-in embeddings
- **Function**:
  - Store chunks with metadata (source, page, timestamp)
  - Retrieve top-K relevant chunks for a query
  - Persist index to disk (auto-save every N insertions)
- **RAM**: ~200MB for embedding model + index (scales with docs stored)
- **⚠️ 4GB constraint**: Use Ollama embeddings API instead of loading a separate model to save ~200MB RAM

#### 3e. Multi-Paper Synthesizer (`tools/synthesizer.py`)
- **Function**: Given multiple retrieved chunks on a topic, produce a synthesis
- **Strategy**:
  - Retrieve relevant chunks from FAISS
  - Group by source paper
  - Feed to LLM with synthesis prompt
  - Output structured comparison / summary
- **RAM**: Negligible (just prompt construction)

---

## RAM Budget (4GB Total)

| Component              | Estimated RAM |
|------------------------|---------------|
| Linux OS + services    | ~500MB        |
| Ollama + Qwen 1.5B    | ~1.5GB        |
| Python process         | ~100MB        |
| FAISS index (10K docs) | ~200MB        |
| Ollama embeddings      | (shared with Ollama) |
| PDF processing (peak)  | ~100MB        |
| **Total**              | **~2.4GB**    |
| **Headroom**           | **~1.6GB**    |

> If using Qwen 3B: add ~1GB → still fits with ~600MB headroom.
> Recommendation: Start with `qwen2.5:1.5b`, upgrade to 3B if quality is insufficient.

---

## One-Shot Prompt Design

The one-shot prompt should contain:
1. **Goal**: What to research/build (clear deliverable)
2. **Scope**: Boundaries (time period, domains, depth)
3. **Output format**: What the final output looks like
4. **Constraints**: Max papers, focus areas, exclusions

### Example One-Shot Prompt:
```
GOAL: Produce a comprehensive literature survey on "Retrieval-Augmented Generation (RAG) 
for domain-specific applications" covering papers from 2023-2025.

SCOPE:
- Search Arxiv for relevant papers (minimum 20, maximum 50)
- Read and extract key findings from each paper
- Organize by sub-topics: medical RAG, legal RAG, code RAG, scientific RAG
- Include comparison tables

OUTPUT: A markdown document at outputs/survey.md with:
- Executive summary (500 words)
- Per-topic sections with citations
- Comparison table of approaches
- Future directions section
- Full bibliography

CONSTRAINTS:
- Prioritize papers with >10 citations or from top venues
- Skip papers not in English
- Time budget: 12 hours
- Step budget: 400 steps
```

---

## Setup Instructions (Linux Laptop)

### Prerequisites
```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull model
ollama pull qwen2.5:1.5b

# Install Python dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### requirements.txt
```
ollama>=0.4.0
duckduckgo-search>=6.0.0
arxiv>=2.1.0
pymupdf>=1.24.0
faiss-cpu>=1.8.0
pyyaml>=6.0
rich>=13.0          # Pretty logging
```

### Running
```bash
# Start Ollama in background
ollama serve &

# Run the agent with your one-shot prompt
python main.py --prompt "prompts/my_research_goal.txt" --hours 12

# Or inline
python main.py --prompt "Research RAG techniques..." --hours 8
```

---

## Key Design Decisions for 4GB RAM

1. **No separate embedding model** — Use Ollama's `/api/embed` endpoint (shares memory with LLM)
2. **Sequential PDF processing** — One at a time, release memory immediately
3. **FAISS flat index** — No fancy HNSW; flat index is fine for <50K vectors
4. **Qwen 1.5B default** — Smallest viable reasoning model; upgrade path to 3B
5. **Disk-backed state** — Checkpoint everything to disk, minimal in-memory state
6. **No GPU assumed** — CPU-only inference (slow but works on any laptop)

---

## Execution Phases (What the Agent Does Over 8-16 Hours)

### Phase 1: Planning (Steps 1-10, ~5 min)
- Parse the one-shot prompt
- Break goal into sub-tasks
- Create a research plan

### Phase 2: Discovery (Steps 11-100, ~2-4 hours)
- Search Arxiv for relevant papers
- Web search for supplementary materials
- Build a paper queue (prioritized)

### Phase 3: Deep Reading (Steps 101-300, ~4-8 hours)
- Download and read papers one by one
- Extract key findings, methods, results
- Store chunks in FAISS memory
- Periodic synthesis of what's been learned

### Phase 4: Synthesis (Steps 301-400, ~2-4 hours)
- Retrieve relevant chunks per topic
- Generate section-by-section output
- Build comparison tables
- Write executive summary

### Phase 5: Finalization (Steps 401-420, ~30 min)
- Compile final document
- Generate bibliography
- Self-review and polish
- Save to outputs/

---

## Crash Recovery & Reliability

- **Checkpoint every 10 steps**: Save current step, plan, tool queue, FAISS index
- **Resume from checkpoint**: `python main.py --resume`
- **Graceful shutdown on SIGTERM**: Finish current step, save state
- **Tool failure isolation**: One tool failing doesn't crash the loop
- **Logging**: All actions logged to `outputs/agent_log.jsonl`

---

## Future Enhancements (If RAM Allows)

- [ ] Code execution tool (sandbox for testing code snippets)
- [ ] Citation graph exploration (follow references)
- [ ] Multi-agent: separate planner and executor
- [ ] Web page reader (full article text, not just snippets)
- [ ] Human-in-the-loop checkpoints (Telegram/email notifications)

---

## Next Steps

1. **Create `llm.py`** — Ollama client wrapper with JSON mode
2. **Create `main.py`** — Basic ReAct loop with checkpoint/resume
3. **Implement tools one by one** (web → arxiv → pdf → memory → synthesizer)
4. **Test with a simple 1-hour prompt** on the Linux laptop
5. **Iterate on prompt engineering** for better autonomous behavior
6. **Run the full 8-16 hour test**
