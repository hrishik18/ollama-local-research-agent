# score_iteration

USE WHEN: After a long iteration completes, you want an LLM-judged qualitative score
to complement the deterministic metrics. Use sparingly (one call per iteration is
plenty) — this is meant for the post-run reflection, not the main loop.

## TEMPLATE

You are evaluating ONE iteration of an autonomous research agent's output.

GOAL the agent was asked to achieve:
{goal}

FINAL OUTPUT the agent produced (truncated to first 8000 chars):
{final_md}

DETERMINISTIC METRICS already computed for this iteration:
{metrics}

Score this iteration on the following 5 dimensions, EACH 0-10:
1. completeness — does it cover the goal end-to-end?
2. citation_quality — are claims backed by real sources, not hand-waving?
3. depth — does it go beyond surface paraphrase?
4. coherence — is the structure logical and easy to follow?
5. novelty — does it surface insights, not just summarize widely-known facts?

Return JSON with:
- "scores": {"completeness": int, "citation_quality": int, "depth": int, "coherence": int, "novelty": int}
- "overall": float (weighted: completeness×0.3 + citations×0.25 + depth×0.2 + coherence×0.15 + novelty×0.1, on 0-10 scale)
- "verdict": "better_than_prev" | "similar_to_prev" | "worse_than_prev" | "no_prev"
- "top_gap": one specific concrete gap the next iteration should address (1 sentence)
- "best_aspect": what this iteration did well (1 sentence)

Return ONLY valid JSON.
