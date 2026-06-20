# generate_search_queries

USE WHEN: You're entering a new sub-topic and need a small set of well-formed search
queries to drive discovery (instead of one vague query).

## TEMPLATE

You are planning targeted searches for the topic: {topic}

Context / what we already know: {context}

Generate 4-6 highly specific search queries that together would give good coverage of
this topic. Each query should:
- be short (4-10 words)
- use terminology that appears in actual paper titles, not chat-style phrasing
- target a DIFFERENT angle (don't paraphrase the same query)
- include at least one query with a date qualifier (e.g. "2024") and one with a method
  qualifier (e.g. "benchmark", "survey", "evaluation")

Return JSON with:
- "queries": list of {"query": string, "intent": string (1 sentence on what it targets), "tool": "arxiv" | "semantic_scholar" | "web" | "github"}

Return ONLY valid JSON.
