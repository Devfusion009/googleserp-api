"""Fetch one Google results page with a real browser and wait for the AI Overview.

Never clicks anything that navigates away; only 'Show more' / 'Show all'
buttons (no href) inside the AI Overview block. Once the page is captured, the
/goto result links the response needs are resolved to their destinations
(app/goto_resolver.py) while the page and its proxy session are still open.
"""
import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeout
from selectolax.parser import HTMLParser

from .browser import PagePool, PageSlot
from .classify import HIDDEN_MARK, AioState, Classification, classify_page
from .config import Settings
from .goto_resolver import resolve_goto
from .parsers.registry import goto_tokens_needed

log = logging.getLogger("serp.fetcher")

# Runs in the page. Mirrors classify.find_aio_root so both agree on the block.
_AIO_ROOT_JS = r"""
  const aioRoot = () => {
    const head = [...document.querySelectorAll('h1,h2,[role=heading]')]
      .find(h => (h.textContent || '').trim().toLowerCase() === 'ai overview');
    if (!head) return null;
    let node = head;
    for (let i = 0; i < 8 && node.parentElement; i++) {
      node = node.parentElement;
      if ((node.innerText || '').trim().length > 200) break;
    }
    return node;
  };
"""

AIO_PROBE_JS = r"""
() => {""" + _AIO_ROOT_JS + r"""
  const node = aioRoot();
  if (!node) return {present: false};
  const text = (node.innerText || '').trim();
  const busy = !!node.querySelector('[aria-busy=true],[role=progressbar]');
  const clickable = [...node.querySelectorAll('[role=button],button')]
    .filter(b => !b.closest('a[href]') && !b.hasAttribute('href'))
    .filter(b => b.offsetParent !== null)
    .filter(b => ['show more', 'show all'].includes((b.innerText || b.getAttribute('aria-label') || '').trim().toLowerCase()));
  clickable.forEach((b, i) => b.setAttribute('data-serp-click', String(i)));
  return {present: true, len: text.length, busy, buttons: clickable.map(b => (b.innerText || b.getAttribute('aria-label')).trim())};
}
"""

# Stamps classify.HIDDEN_MARK on the outermost unrendered elements inside the AI
# Overview, so the saved HTML says what the browser actually hid - including
# elements hidden by a stylesheet rather than an inline style. Only the
# classifier reads the mark; parsers ignore it.
MARK_HIDDEN_JS = r"""
(mark) => {""" + _AIO_ROOT_JS + r"""
  const root = aioRoot();
  if (!root || !root.checkVisibility) return 0;
  const shown = el => el.checkVisibility({visibilityProperty: true});
  let n = 0;
  for (const el of root.querySelectorAll('*')) {
    if (!shown(el) && (!el.parentElement || shown(el.parentElement))) { el.setAttribute(mark, ''); n++; }
  }
  return n;
}
"""


@dataclass
class FetchResult:
    url_sent: str
    final_url: str | None = None
    html: str | None = None
    classification: Classification = Classification.ok
    reason: str = ""
    aio_state: AioState = AioState.absent
    timings: dict = field(default_factory=dict)
    artifact_dir: str | None = None
    proxy: str | None = None
    links: dict[str, str] = field(default_factory=dict)  # /goto token -> destination


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _slug(url: str) -> str:
    m = re.search(r"[?&]q=([^&#]*)", url)
    return re.sub(r"[^a-z0-9]+", "_", (m.group(1) if m else "page").lower().replace("%20", " "))[:50].strip("_")


class Fetcher:
    def __init__(self, settings: Settings, browsers: PagePool):
        self.s = settings
        self.browsers = browsers

    async def fetch(self, url: str, country: str | None, language: str | None) -> FetchResult:
        attempts = 1 + max(0, self.s.max_retries)
        result = None
        for attempt in range(attempts):
            result = await self._fetch_once(url, country, language)
            result.timings["attempt"] = attempt + 1
            if result.classification not in (Classification.timeout, Classification.network_error):
                break
            log.warning("retryable failure %s (attempt %d/%d)", result.classification.value, attempt + 1, attempts)
        return result

    async def _fetch_once(self, url: str, country: str | None, language: str | None) -> FetchResult:
        res = FetchResult(url_sent=url)
        t0 = time.perf_counter()
        try:
            async with self.browsers.page(country, language) as slot:
                res.proxy = slot.proxy
                net = getattr(slot, "net", None)
                if net is not None:
                    net.reset()
                try:
                    await asyncio.wait_for(self._run(slot, url, res, t0), timeout=self.s.request_deadline_ms / 1000)
                finally:
                    if net is not None:
                        res.timings["bytes_in"], res.timings["net_requests"] = net.bytes, net.requests
        except (asyncio.TimeoutError, PlaywrightTimeout) as e:
            res.classification, res.reason = Classification.timeout, f"timed out: {str(e)[:200] or 'request deadline'}"
        except PlaywrightError as e:
            res.classification, res.reason = Classification.network_error, f"browser/network error: {str(e).splitlines()[0][:200]}"
        res.timings["total_ms"] = _ms(t0)
        log.info("done url=%s class=%s aio=%s reason=%s timings=%s",
                 url, res.classification.value, res.aio_state.value, res.reason, res.timings)
        return res

    async def _run(self, slot: PageSlot, url: str, res: FetchResult, t0: float) -> None:
        page = slot.page
        log.info("navigate url_sent=%s", url)
        await page.goto(url, wait_until="domcontentloaded", timeout=self.s.nav_timeout_ms)
        res.timings["nav_ms"] = _ms(t0)
        res.final_url = page.url
        if page.url != url:
            log.info("final url differs: %s", page.url)

        early = classify_page(page.url, await page.content())
        if early.classification in (Classification.blocked_captcha, Classification.consent_wall):
            res.classification, res.reason = early.classification, early.reason
            await self._finish(page, res)
            return

        try:
            await page.wait_for_selector("#search, #rso", timeout=self.s.nav_timeout_ms)
        except PlaywrightTimeout:
            res.html = await page.content()
            v = classify_page(page.url, res.html)
            res.classification = v.classification if v.classification is not Classification.ok else Classification.degraded_page
            res.reason = v.reason if v.classification is not Classification.ok else "results container never appeared"
            await self._finish(page, res, capture=False)
            return
        res.timings["results_ms"] = _ms(t0)

        aio_ok, aio_reason = await self._wait_aio(page)
        res.timings["aio_ms"] = _ms(t0)

        await page.evaluate(MARK_HIDDEN_JS, HIDDEN_MARK)
        res.html = await page.content()
        res.final_url = page.url
        v = classify_page(page.url, res.html)
        res.classification, res.reason, res.aio_state = v.classification, v.reason, v.aio_state
        if not aio_ok and v.classification is Classification.ok:
            res.classification, res.reason, res.aio_state = Classification.aio_incomplete, aio_reason, AioState.incomplete
        if res.classification is Classification.ok:
            await self._resolve_links(slot, res, t0)
        await self._finish(page, res, capture=False)

    async def _resolve_links(self, slot: PageSlot, res: FetchResult, t0: float) -> None:
        """Resolve the /goto links the response will contain. Unresolved ones are
        left out of res.links; the orchestrator then fails the page as incomplete."""
        tokens = goto_tokens_needed(HTMLParser(res.html or ""))
        res.timings["links_needed"] = len(tokens)
        if not tokens:
            return
        outcome = await resolve_goto(slot.page, getattr(slot, "net", None), tokens, self.s)
        res.links = outcome.resolved
        res.timings["links_resolved"] = len(outcome.resolved)
        res.timings["links_in_page"] = outcome.in_page
        res.timings["links_ms"] = _ms(t0)
        if outcome.blocked:
            res.classification = Classification.blocked_captcha
            res.reason = "Google answered a /goto link with its /sorry/ (unusual traffic) page"

    async def _wait_aio(self, page: Page) -> tuple[bool, str]:
        """Returns (ok, reason). ok=False only when an AI Overview is present but not finished."""
        # 1) appear: poll until the AIO heading shows, up to AIO_APPEAR_WAIT_MS.
        deadline = time.perf_counter() + self.s.aio_appear_wait_ms / 1000
        probe = await page.evaluate(AIO_PROBE_JS)
        while not probe["present"] and time.perf_counter() < deadline:
            await page.wait_for_timeout(100)
            probe = await page.evaluate(AIO_PROBE_JS)
        if not probe["present"]:
            return True, "no AI Overview"

        # 2) finish: not busy and text length stable for ~300 ms, up to AIO_MAX_WAIT_MS.
        end = time.perf_counter() + self.s.aio_max_wait_ms / 1000
        clicked: set[str] = set()
        last_len, stable_since = -1, time.perf_counter()
        while time.perf_counter() < end:
            probe = await page.evaluate(AIO_PROBE_JS)
            if not probe["present"]:
                return False, "AI Overview disappeared while loading"
            now = time.perf_counter()
            if probe["len"] != last_len or probe["busy"]:
                last_len, stable_since = probe["len"], now
            elif now - stable_since >= 0.3:
                # 3) expand once each: 'Show more', then 'Show all' (sources)
                todo = [(i, b) for i, b in enumerate(probe["buttons"]) if b.lower() not in clicked]
                if not todo:
                    return True, "AI Overview complete"
                i, label = todo[0]
                clicked.add(label.lower())
                before = page.url
                try:
                    await page.locator(f'[data-serp-click="{i}"]').first.click(timeout=2000)
                except PlaywrightError as e:
                    log.warning("could not click '%s': %s", label, str(e).splitlines()[0])
                if page.url != before:
                    return False, f"clicking '{label}' navigated away"
                last_len, stable_since = -1, time.perf_counter()
            await page.wait_for_timeout(100)
        return False, f"AI Overview not finished within {self.s.aio_max_wait_ms} ms"

    async def _finish(self, page: Page, res: FetchResult, capture: bool = True) -> None:
        if capture or res.html is None:
            res.html = await page.content()
        if self.s.debug_artifacts:
            out = Path(self.s.artifacts_dir) / f"{time.strftime('%Y%m%d_%H%M%S')}_{_slug(res.url_sent)}"
            out.mkdir(parents=True, exist_ok=True)
            (out / "page.html").write_text(res.html or "", encoding="utf-8")
            try:
                await page.screenshot(path=str(out / "screenshot.png"), full_page=True, timeout=5000)
            except PlaywrightError as e:
                log.warning("screenshot failed: %s", str(e).splitlines()[0])
            res.artifact_dir = str(out)
