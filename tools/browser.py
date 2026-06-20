"""Browser-automation tool via Playwright.

WHY this exists:
- `web_fetch` uses requests+BeautifulSoup. It can't render JavaScript, so SPA
  docs, dynamic dashboards, sites that lazy-load content, and many news sites
  return empty bodies. A browser-driven fetch sees what a human sees.
- Many tutorials/docs sites (e.g. modern React docs, Vercel-hosted sites)
  serve a near-empty HTML shell to bots. Playwright Chromium gets the real
  rendered text.
- A skill (`skills/browser_automation.md`) tells the agent WHEN to reach for
  this vs. plain `web_fetch`.

4 GB RAM caveats — this is opt-in and aggressive about cleanup:
- Disabled by default in config.yaml. Install is a separate step
  (`pip install playwright && playwright install chromium`).
- We launch + close the browser PER CALL. No long-lived browser context.
  Each call costs ~5-8 s overhead but doesn't sit on RAM between calls.
- Headless, single-page, JS-only (images/css/fonts blocked) → ~150 MB peak.
- Per-call hard timeout so a stuck page can't hang the overnight run.
- Lazy import. If Playwright isn't installed the tool returns
  `{"error": "playwright not installed", ...}` — never crashes the agent.

Public API mirrors `web_fetch`:
    tool.fetch(url) -> {"url", "title", "text", "n_chars"} or {"error"}
    tool.extract(url, css_selectors) -> {"url", "extracted": {sel: [text,...]}}
    tool.screenshot(url, path) -> {"url", "screenshot": path}
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)


# Lazy import. None means "not installed → tool is a no-op error".
_PW_AVAILABLE: Optional[bool] = None


def _check_playwright() -> bool:
    global _PW_AVAILABLE
    if _PW_AVAILABLE is not None:
        return _PW_AVAILABLE
    try:
        import playwright  # noqa: F401
        from playwright.sync_api import sync_playwright  # noqa: F401
        _PW_AVAILABLE = True
    except Exception as e:
        log.info("playwright not available (%s); BrowserTool will return errors", e)
        _PW_AVAILABLE = False
    return _PW_AVAILABLE


# Resources we block to keep RAM low and load fast on a 4 GB box.
_BLOCK_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}


class BrowserTool:
    name = "browser"
    description = (
        "Headless browser (Playwright Chromium). Use ONLY when web_fetch returns "
        "empty/login-wall/JS-shell content — it's 10x slower and uses ~150MB RAM."
    )

    def __init__(
        self,
        enabled: bool = False,
        engine: str = "chromium",
        headless: bool = True,
        nav_timeout_ms: int = 30000,
        wait_after_load_ms: int = 800,
        max_chars: int = 20000,
        block_resources: bool = True,
        screenshot_dir: str = "state/screenshots",
    ) -> None:
        self.enabled = enabled
        self.engine = engine
        self.headless = headless
        self.nav_timeout_ms = nav_timeout_ms
        self.wait_after_load_ms = wait_after_load_ms
        self.max_chars = max_chars
        self.block_resources = block_resources
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    # ---------- internal ----------

    def _disabled_response(self, url: str) -> dict[str, Any]:
        return {
            "url": url,
            "error": "browser tool disabled (set tools.browser.enabled=true in config.yaml)",
            "text": "",
        }

    def _not_installed_response(self, url: str) -> dict[str, Any]:
        return {
            "url": url,
            "error": "playwright not installed. Run: pip install playwright && playwright install chromium",
            "text": "",
        }

    def _new_context(self, p):
        """Launch + return (browser, context, page) tuple. Caller must close browser."""
        if self.engine == "firefox":
            browser = p.firefox.launch(headless=self.headless)
        elif self.engine == "webkit":
            browser = p.webkit.launch(headless=self.headless)
        else:
            browser = p.chromium.launch(headless=self.headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) ollama-research-agent/0.5 (Playwright)",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        page.set_default_navigation_timeout(self.nav_timeout_ms)
        if self.block_resources:
            page.route(
                "**/*",
                lambda route: (
                    route.abort()
                    if route.request.resource_type in _BLOCK_RESOURCE_TYPES
                    else route.continue_()
                ),
            )
        return browser, context, page

    # ---------- public ----------

    def fetch(self, url: str) -> dict[str, Any]:
        """Render `url` with a real browser, return readable text + title."""
        if not self.enabled:
            return self._disabled_response(url)
        if not _check_playwright():
            return self._not_installed_response(url)

        from playwright.sync_api import sync_playwright

        t0 = time.time()
        try:
            with sync_playwright() as p:
                browser, context, page = self._new_context(p)
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    # Tiny wait so client-side scripts can hydrate the DOM.
                    page.wait_for_timeout(self.wait_after_load_ms)
                    title = page.title() or ""
                    text = page.evaluate("document.body ? document.body.innerText : ''")
                    text = (text or "").strip()
                    if len(text) > self.max_chars:
                        text = text[: self.max_chars]
                    return {
                        "url": url,
                        "title": title.strip(),
                        "text": text,
                        "n_chars": len(text),
                        "elapsed_s": round(time.time() - t0, 2),
                        "engine": self.engine,
                    }
                finally:
                    browser.close()
        except Exception as e:
            log.warning("browser fetch failed for %s: %s", url, e)
            return {"url": url, "error": str(e), "text": "", "elapsed_s": round(time.time() - t0, 2)}

    def extract(self, url: str, css_selectors: list[str]) -> dict[str, Any]:
        """Render `url` and pull innerText from each CSS selector."""
        if not self.enabled:
            return self._disabled_response(url)
        if not _check_playwright():
            return self._not_installed_response(url)

        from playwright.sync_api import sync_playwright

        out: dict[str, list[str]] = {sel: [] for sel in css_selectors}
        t0 = time.time()
        try:
            with sync_playwright() as p:
                browser, context, page = self._new_context(p)
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_timeout(self.wait_after_load_ms)
                    for sel in css_selectors:
                        try:
                            elements = page.locator(sel).all()
                            out[sel] = [(el.inner_text() or "").strip() for el in elements][:50]
                        except Exception as e:
                            out[sel] = [f"<selector error: {e}>"]
                    return {
                        "url": url,
                        "extracted": out,
                        "elapsed_s": round(time.time() - t0, 2),
                    }
                finally:
                    browser.close()
        except Exception as e:
            log.warning("browser extract failed for %s: %s", url, e)
            return {"url": url, "error": str(e), "extracted": out}

    def screenshot(self, url: str, name: Optional[str] = None) -> dict[str, Any]:
        """Render `url` and save a PNG to `state/screenshots/`."""
        if not self.enabled:
            return self._disabled_response(url)
        if not _check_playwright():
            return self._not_installed_response(url)

        from playwright.sync_api import sync_playwright

        fname = name or f"shot_{int(time.time())}.png"
        path = self.screenshot_dir / fname
        try:
            with sync_playwright() as p:
                browser, context, page = self._new_context(p)
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_timeout(self.wait_after_load_ms)
                    page.screenshot(path=str(path), full_page=False)
                    return {"url": url, "screenshot": str(path)}
                finally:
                    browser.close()
        except Exception as e:
            log.warning("browser screenshot failed for %s: %s", url, e)
            return {"url": url, "error": str(e)}

    # Generic dispatch so the ReAct loop can call this like any other tool.
    def run(self, url: str, action: str = "fetch", **kwargs) -> dict[str, Any]:
        if action == "extract":
            return self.extract(url, kwargs.get("css_selectors", ["body"]))
        if action == "screenshot":
            return self.screenshot(url, name=kwargs.get("name"))
        return self.fetch(url)
