# Experiment 001 — DarkForge & Phoenix repo investigation

**Date:** 2026-06-20
**Agent task:** Find the "dark forge" and "phoenix" repos by Sham Sridhar (Microsoft AI community / Vibe community) and integrate with `ollama_local_setup`.

## Findings

### 1. DarkForge — FOUND

- **Repo:** [`shyamsridhar123/DarkForge`](https://github.com/shyamsridhar123/DarkForge)
- **Description:** "100× your distributed AI engineering. DarkForge runs disposable code in Kata-isolated sandboxes on Azure, attributed to a real engineer, in safe parallel."
- **Stack:** Python · Kubernetes (AKS) · Kata Containers · Bicep · Helm · Azure Foundry · Anthropic Claude / Kimi / OpenAI
- **Last updated:** 2026-06-03
- **Topics:** agentic-ai, code-sandbox, kata-containers, secure-execution, workload-identity

### Integration verdict: ❌ NOT COMPATIBLE with the local 4GB-RAM target

DarkForge is fundamentally **a cloud-scale Kubernetes platform** for running disposable code in Kata-isolated sandboxes on Azure. The deployment requires:
- Azure subscription + AKS cluster
- Kata Containers runtime (nested virtualization on the cluster nodes)
- Helm + Bicep + workload identity
- Calls hosted LLM APIs (Claude, Kimi, OpenAI) — not Ollama

A 4GB Linux laptop running CPU-only Qwen is the **opposite end of the spectrum**: single-process, no cluster, no hosted LLMs. There is no meaningful "install and use with ollama_local_setup" path — they solve different problems.

What we CAN borrow from DarkForge philosophically:
- The "disposable code execution attributed to an engineer" pattern → a future
  `tools/code_runner.py` that runs LLM-generated code in a local subprocess sandbox.
- The "parallel safe execution" idea → we can run independent tool calls in parallel
  with `concurrent.futures`.

These are noted as future enhancements, not shipped here.

### 2. Phoenix — AMBIGUOUS

Searched `user:shyamsridhar123` for any repo named/containing "phoenix" — **no repo
match**. Only incidental mentions of "Phoenix" the U.S. city in vocab files /
location demo data.

The single closest meaningful match across all of GitHub is
[`Arize-ai/phoenix`](https://github.com/Arize-ai/phoenix) — 10,197★ AI Observability
& Evaluation platform (LLM tracing, evals, dataset management). **This is a different
author** but is highly relevant to our agent: it instruments LLM calls and shows
traces, exactly what a slow long-horizon agent benefits from.

### Integration verdict: ✅ OPTIONAL TRACING INTEGRATION

Arize Phoenix is `pip install arize-phoenix-otel` lightweight; it can run locally and
collect OpenTelemetry traces from our Ollama calls. **Added as an optional integration**
(see `tools/phoenix_tracer.py` + `config.yaml` flag) so the user can opt in:

```yaml
tracing:
  enabled: false  # set to true to enable Arize Phoenix tracing
  endpoint: "http://localhost:6006/v1/traces"
```

Then run `phoenix serve` separately and traces appear in its UI.

## Experiments performed this iteration

1. **GitHub search via MCP** — confirmed no Phoenix repo from `shyamsridhar123`
2. **Reviewed DarkForge README/topics** — confirmed cloud-Kubernetes scope
3. **Surveyed adjacent shyamsridhar123 repos** for inspiration. Notable findings:
   - `agentsmith-cli`: multi-agent generator from any GitHub repo (could inspire our skills system → DONE in v0.2)
   - `sharkbait`: AI CLI with 33+ tools (validates our multi-tool approach)
   - `harness`: white paper arguing the orchestration layer determines agent success (aligns with our design)
   - `AlltheVibes-WildHackathon`: likely the "vibe community" referenced — Python, multi-fork hackathon repo

## Decisions made

| Question | Decision |
|----------|----------|
| Install DarkForge locally? | No — it's a cloud K8s platform, not compatible with 4GB Linux laptop |
| Install Phoenix locally? | Yes (Arize variant) as an **optional** opt-in observability integration |
| Run experiments with DarkForge? | No — would require Azure subscription + cluster |
| Borrow ideas? | Yes — note disposable-sandbox pattern as future work |

## Next iteration suggestions

- If user actually meant a different "phoenix" repo (e.g. a private internal Microsoft repo), they need to provide the URL explicitly
- If user wants to migrate to cloud-scale, DarkForge would be the right baseline — but that's a different project, not an extension of this one
- The Phoenix tracing integration can be activated with one config flag
