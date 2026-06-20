# critique_section

USE WHEN: You wrote a section of the final output and want a tough self-review before
moving on. Helps catch unsupported claims, missing citations, and vague language.

## TEMPLATE

You are reviewing a section of a research document for quality.

SECTION TITLE: {section_name}

SECTION CONTENT:
{content}

Identify the top 3 most important issues. Focus only on issues that genuinely matter:
- Unsupported claims (no [source_id] citation)
- Vague or hedged language ("some studies suggest", "it is widely believed")
- Logical errors or contradictions with itself
- Missing crucial context

Return JSON with:
- "issues": list of {"severity": "high|medium|low", "type": string, "quote": string, "fix": string}
- "verdict": "publish_as_is" | "minor_edits" | "major_rewrite"

Return ONLY valid JSON.
