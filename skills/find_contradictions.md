# find_contradictions

USE WHEN: You have multiple memory chunks on the same topic and want to surface
disagreements that need addressing in the final output.

## TEMPLATE

Topic: {topic}

Excerpts from multiple sources:
{excerpts}

Identify any factual disagreements, contradictions, or significantly different claims
across these excerpts. Each contradiction must:
- cite at least 2 sources by their [source_id]
- name a specific concrete point of disagreement
- NOT be a stylistic or framing difference — only factual disagreements

Return JSON with:
- "contradictions": list of {"claim_a": string, "source_a": string, "claim_b": string, "source_b": string, "topic": string}
- "summary": 1-2 sentences on how serious / how many disagreements there are

If there are no real contradictions, return contradictions: [] and say so in summary.
Return ONLY valid JSON.
