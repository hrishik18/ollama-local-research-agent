# extract_paper_findings

USE WHEN: You have a paper title + abstract (or one PDF chunk) and need structured
findings to store in memory.

## TEMPLATE

You will extract structured findings from a research excerpt.

EXCERPT (source: {source_id}):
{text}

Return JSON with these keys:
- "problem": The problem the paper addresses (1 sentence)
- "method": The proposed approach (1-2 sentences)
- "key_findings": List of 3-5 short bullet strings
- "limitations": Stated limitations or future work (1-2 sentences, or null if unstated)
- "domain": One of: medical, legal, code, scientific, general, other
- "year": Year if mentioned, else null

Be concise. Use the exact terminology from the excerpt. If a field cannot be determined,
use null. Return ONLY valid JSON, no prose.
