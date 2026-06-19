# summarize_chunks

USE WHEN: You retrieved several memory chunks on a topic and need a tight summary.

## TEMPLATE

Topic: {topic}

Retrieved chunks:
{chunks}

Produce a tight, factual summary as 5-8 markdown bullet points. Each bullet must:
- be one sentence
- cite its source as [source_id] inline
- contain a concrete fact, finding, or claim — NOT meta-commentary

Below the bullets, list any open questions or contradictions you noticed (1-3 lines, or
"none" if there are none).
