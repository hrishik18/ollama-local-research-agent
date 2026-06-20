# browser_automation

USE WHEN: you have a URL but plain `web_fetch` returned an empty body, a tiny
JS shell (e.g. `<div id="root"></div>`), a login wall, a Cloudflare challenge,
or a page where the headline/abstract/code-block you wanted was missing.
Modern SPA docs (React/Next/Vercel-hosted), dashboards, dynamic search result
pages, and JS-heavy news sites all need a real browser to see the same text a
human would. The `browser` tool (Playwright + headless Chromium) renders the
page and returns the rendered text.

DO NOT USE for:
- Static pages — `web_fetch` is 10x faster and ~150 MB lighter on RAM.
- Sites that already worked with `web_fetch`.
- ArXiv/Wikipedia/Semantic Scholar — use the dedicated tools.
- Anything you can answer from existing memory — query memory first.

The browser tool is OFF by default (config.yaml → `tools.browser.enabled`).
If the orchestrator says it is disabled or Playwright is not installed,
fall back to `web_fetch` and note the limitation in your reasoning.

## TEMPLATE

You decided to fetch a URL with the browser tool. The rendered page returned:

URL: {url}
TITLE: {title}
ELAPSED: {elapsed_s} seconds
TEXT (truncated to first {n_chars} chars):
{text}

The user's overall goal:
{goal}

The specific reason you needed a browser-rendered fetch:
{reason}

Now produce JSON with:
- "answered_question": true | false — does this page actually answer the
  reason above?
- "key_findings": list of 1-5 short bullet strings extracted from the page,
  each citing the URL.
- "follow_up_links": list of {"url": str, "why": str} for at most 3 URLs that
  appeared in the page text and look genuinely worth visiting next. Pass
  ONLY absolute URLs you can see in the text. Empty list is fine.
- "store_in_memory": true | false — is the extracted content worth
  persisting in FAISS? Set false for navigation pages, 404s, paywalls.
- "memory_snippet": null OR a self-contained ≤300-word paragraph suitable
  for memory storage (NOT the raw page — synthesize). Include the URL.
- "next_action": one of: "extract_with_selectors" | "screenshot" |
  "use_web_fetch_instead" | "give_up" | "done"

Return ONLY valid JSON. No prose, no markdown fences.
