# Todo

Prioritized backlog for the autonomous local research agent. Tick items as you ship them.
Generated 2026-06-20 after v0.4.

Legend: `🔥` started · `⏳` next up · `💡` idea

---

## Tier 1 — high value, low effort (do these next)

- [ ] **Real end-to-end Linux run.** Pull the repo on the 4 GB laptop, run `main.py` against a real goal, watch for: Ollama OOM, JSON parse failures from Qwen, retry storms, thermal aborts. This is where every real bug lives.
  - **Path A — WSL2 on Windows:** `wsl --install -d Ubuntu-22.04`, then `bash scripts/wsl_setup.sh`. Cap RAM via `%USERPROFILE%\.wslconfig`.
  - **Path B — Azure VM:** `./scripts/azure_vm_setup.sh` (needs `az` CLI + subscription). `--destroy` to tear down.
  - **Path C — actual target laptop:** `git pull && bash scripts/wsl_setup.sh` (script works on any Ubuntu/Debian, not just WSL). This is the only path that validates thermal-zone reads and `notify-send`.
- [x] **Run-finished notifications.** `tools/notifier.py` shipped (ntfy.sh + `notify-send` + console fallback). _Still TODO:_ wire into `main.py` `finally` block + add `notifications:` section to `config.yaml`.
- [x] **Disk rotation.** `scripts/cleanup.py` shipped (`--keep-last`, `--max-age-days`, `--pdf-age-days`, log rotation, dry-run by default). _Still TODO:_ add a cron / systemd-timer example to README.
- [ ] **Prompt template library.** `prompts/templates/research_paper.md`, `competitive_analysis.md`, `tech_deep_dive.md`, `literature_review.md`. Plus a `scripts/use_template.py NAME` that copies the chosen template to `prompt.md`.

## Tier 2 — high value, medium effort

- [ ] **Native Ollama tool-calling.** Replace "model emits JSON we parse" with Ollama's `tools=[...]` API. Biggest reliability win — JSON parse failures are currently the #1 long-run killer.
- [ ] **Output diff in dashboard.** Side-by-side `difflib.HtmlDiff` between `iteration_N-1/final.md` and `iteration_N/final.md` inside the drill-down modal.
- [ ] **Eval / golden-question suite.** `evals/questions.yaml` with 10-20 fixed (query, expected_keywords) entries. `python evals/run.py` indexes a fixture corpus, runs each query, scores keyword recall@k. Run on every prompt/skill change.
- [ ] **Auto-recovery from Ollama crashes.** Wrap LLM client: on connection error, wait + ping `/api/tags`, retry up to N times before aborting. Single hiccup at hour 4 should not kill a 16 h run.
- [ ] **Compare-runs view in dashboard.** Two-iteration picker → side-by-side metric table + output diff. Useful for A/B'ing prompt changes.

## Tier 3 — medium value, medium effort

- [ ] **Plugin discovery for tools.** Replace eager imports in `tools/__init__.py` with `pkgutil.iter_modules` + a `Tool` base class. Drop `tools/my_tool.py` → auto-registers, no edits to 4 files.
- [ ] **Streaming step events to the dashboard.** SSE endpoint that pushes `step`/`reflect` events live. Turns the dashboard into a real-time tail instead of poll-every-60-s.
- [ ] **Better thermal handling.** On thermal warning (not abort), pause the agent for 60-120 s instead of killing it. Pair with a "thermal pause count" in the scorecard.
- [ ] **JSON-schema validation for actions.** Stop runaway model creativity before it consumes tool retries.
- [ ] **Tool-level cost ledger.** Track tokens-in / tokens-out / wall-time per tool call → surfaced as a "where is time going?" chart in dashboard.

## Tier 4 — experimental / nice to have

- [ ] **Local re-ranker** (`cross-encoder/ms-marco-MiniLM-L6-v2`) for memory_search quality. Costs ~80 MB RAM — borderline on 4 GB.
- [ ] **Benchmark `qwen2.5:3b` vs `1.5b`** with the eval suite. If you can spare 1.5 GB headroom, 3B is meaningfully better at long-horizon planning.
- [ ] **Multi-agent mode.** Researcher + critic ping-pong. Probably overkill for 4 GB but interesting.
- [ ] **Goal decomposition skill.** Skill that, given a complex goal, returns a DAG of sub-goals. Agent works through the DAG and marks nodes done. Much better long-horizon coherence.
- [ ] **Persistent memory across runs.** Today FAISS is rebuilt per goal. A `--mode=continuous` that keeps the index warm across goals (with namespacing) so the agent builds up a personal knowledge base over weeks.

## Tier 5 — operational / community

- [ ] **Make the repo public + write-up.** This project is genuinely novel — most "local agent" repos lack RAM/thermal monitoring, scorecards, or a traceability dashboard. HN / r/LocalLLaMA post.
- [ ] **CI on push.** GitHub Actions running `pytest tests/` on PRs. No Ollama needed; the smoke tests run cleanly without it.
- [ ] **Pin dependencies + add `pip-tools`/`uv` lock file.** Currently using `>=`; reproducibility for the 4 GB laptop matters.
- [ ] **`Dockerfile` (optional).** Even on a 4 GB box, a one-command spin-up that mounts `history/` and `prompt.md` would lower the bar.
- [ ] **`docs/ARCHITECTURE.md`** — the FAISS+BM25 hybrid, the prompt-rewrite loop, the scoring rubric, the monitor thresholds. Quick on-ramp for anyone else (or future you).

---

## Currently in-flight (uncommitted local work)

- `tools/notifier.py` — created, not yet hooked into `main.py`
- `scripts/cleanup.py` — created, not yet documented in README

Next session: finish wiring those two, then pick from Tier 1 (real Linux run + prompt templates).
