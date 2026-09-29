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
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeout
from selectolax.parser import HTMLParser

from .browser import PagePool, PageSlot
from .classify import HIDDEN_MARK, AioState, Classification, classify_page
from .config import Settings
from .goto_resolver import GotoResolution, resolve_goto
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

# Expand controls of the AI Overview. After expanding, Google keeps the "Show
# all" element in the DOM (hidden) next to a "Show less" (seen in every saved
# page), so a control's presence says nothing - its visibility, label and
# aria-expanded do.
EXPAND_LABELS = ("show more", "show all")

# Each expand control gets a stable id (data-serp-btn) the first time it is
# seen and keeps it, so a click can be verified on the same element even after
# its label changes ("Show more" -> "Show less") or it is hidden.
AIO_PROBE_JS = r"""
() => {""" + _AIO_ROOT_JS + r"""
  const node = aioRoot();
  if (!node) return {present: false};
  const text = (node.innerText || '').trim();
  const busy = !!node.querySelector('[aria-busy=true],[role=progressbar]');
  const shown = el => el.checkVisibility ? el.checkVisibility({visibilityProperty: true}) : el.offsetParent !== null;
  const labelOf = el => (el.innerText || el.getAttribute('aria-label') || '').trim();
  const buttons = [];
  for (const b of node.querySelectorAll('[role=button],button,[data-serp-btn]')) {
    if (b.closest('a[href]') || b.hasAttribute('href')) continue;
    const label = labelOf(b);
    if (!b.hasAttribute('data-serp-btn')) {
      if (!['show more', 'show all'].includes(label.toLowerCase())) continue;
      window.__serpBtnSeq = (window.__serpBtnSeq || 0) + 1;
      b.setAttribute('data-serp-btn', String(window.__serpBtnSeq));
    }
    buttons.push({id: b.getAttribute('data-serp-btn'), label, visible: shown(b), expanded: b.getAttribute('aria-expanded')});
  }
  return {present: true, len: text.length, busy, buttons};
}
"""

# A click is retried at most this often, and must show its effect within
# EXPAND_VERIFY_MS (all within AIO_MAX_WAIT_MS).
MAX_EXPAND_ATTEMPTS = 3
EXPAND_VERIFY_MS = 1500
CLICK_TIMEOUT_MS = 1000
STABLE_S = 0.3


def _pending_expanders(probe: dict, done: set[str]) -> list[dict]:
    """Visible 'Show more' / 'Show all' controls not yet expanded."""
    return [
        b for b in probe["buttons"]
        if b["visible"] and b["label"].lower() in EXPAND_LABELS and b.get("expanded") != "true" and b["id"] not in done
    ]


def _expansion_seen(before: dict, probe: dict) -> bool:
    """Did clicking `before` (a button from the previous probe) visibly expand
    something? The control is gone or hidden, its label changed (e.g. to "Show
    less"), aria-expanded turned true, or the AI Overview's text grew."""
    if not probe.get("present"):
        return False
    after = next((b for b in probe["buttons"] if b["id"] == before["id"]), None)
    if after is None or not after["visible"]:
        return True
    if after["label"].lower() != before["label"].lower() or after.get("expanded") == "true":
        return True
    return probe["len"] > before["len_before"]

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
    # Requests by kind (netwatch.REQUEST_KINDS, plus goto_fallback), summed over retries.
    usage: dict[str, int] = field(default_factory=dict)
    # Proxy session facts for this request: session id, exit_ip, exit_ip_after,
    # ip_changed, ip_checks / ip_check_bytes.
    session: dict = field(default_factory=dict)
    goto: GotoResolution | None = None  # /goto resolution for this page, if any

    @property
    def requests_used(self) -> int:
        """Requests to Google this fetch cost: page loads (every attempt and
        redirect hop, so retries count), /async/ follow-ups (the AI Overview) and
        /goto link resolutions. Scripts, styles and logging pings are in `usage`
        but not counted here."""
        attempts = self.timings.get("attempt", 1)
        u = self.usage
        return max(u.get("document", 0), attempts) + u.get("async", 0) + u.get("goto", 0) + u.get("goto_fallback", 0)


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


# Summed over retries by Fetcher.fetch.
TRAFFIC_KEYS = ("bytes_in", "net_requests", "out_of_page_requests", "bytes_out_of_page")


def _add_out_of_page_traffic(res: FetchResult) -> None:
    """Fold the traffic of requests made outside the browser - /goto fallback
    requests and exit-IP checks - into bytes_in. The browser's counter can't see
    them; their responses are reconstructed (netwatch.out_of_page_bytes), but
    their connection/TLS overhead can't be measured, so the figure is marked
    partial and consumers add an allowance per request."""
    requests = res.usage.get("goto_fallback", 0) + res.session.get("ip_checks", 0)
    if not requests:
        return
    nbytes = (res.goto.fallback_bytes if res.goto else 0) + res.session.get("ip_check_bytes", 0)
    res.timings["out_of_page_requests"] = requests
    res.timings["bytes_out_of_page"] = nbytes
    res.timings["bytes_in"] = res.timings.get("bytes_in", 0) + nbytes
    res.timings["bytes_in_partial"] = True


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
        usage: Counter = Counter()
        traffic: Counter = Counter()
        partial = ip_changed = False
        for attempt in range(attempts):
            result = await self._fetch_once(url, country, language)
            usage.update(result.usage)
            traffic.update({k: result.timings[k] for k in TRAFFIC_KEYS if k in result.timings})
            partial = partial or bool(result.timings.get("bytes_in_partial"))
            ip_changed = ip_changed or bool(result.session.get("ip_changed"))
            result.timings["attempt"] = attempt + 1
            if result.classification not in (Classification.timeout, Classification.network_error):
                break
            log.warning("retryable failure %s (attempt %d/%d)", result.classification.value, attempt + 1, attempts)
        # A retry costs requests and traffic too: report the totals, not the last attempt's.
        result.usage = dict(usage)
        result.timings.update(traffic)
        if partial:
            result.timings["bytes_in_partial"] = True
        if ip_changed:
            result.session["ip_changed"] = True
        return result

    async def _fetch_once(self, url: str, country: str | None, language: str | None) -> FetchResult:
        res = FetchResult(url_sent=url)
        t0 = time.perf_counter()
        try:
            async with self.browsers.page(country, language) as slot:
                res.proxy = slot.proxy
                # The pool fills in the exit IP after the request (same dict).
                res.session = getattr(slot, "report", None) or {}
                net = getattr(slot, "net", None)
                if net is not None:
                    net.reset()
                try:
                    await asyncio.wait_for(self._run(slot, url, res, t0), timeout=self.s.request_deadline_ms / 1000)
                finally:
                    if net is not None:
                        res.timings["bytes_in"], res.timings["net_requests"] = net.bytes, net.requests
                        res.usage.update({k: v for k, v in net.kinds.items() if v})
                    else:
                        res.usage.setdefault("document", 1)
                    if res.goto is not None and res.goto.fallback_requests:
                        res.usage["goto_fallback"] = res.goto.fallback_requests
                if res.classification in (Classification.blocked_captcha, Classification.consent_wall) and hasattr(slot, "retire"):
                    slot.retire = f"Google answered {res.classification.value} on this session"
        except (asyncio.TimeoutError, PlaywrightTimeout) as e:
            res.classification, res.reason = Classification.timeout, f"timed out: {str(e)[:200] or 'request deadline'}"
        except PlaywrightError as e:
            res.classification, res.reason = Classification.network_error, f"browser/network error: {str(e).splitlines()[0][:200]}"
        _add_out_of_page_traffic(res)
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
        # Created here so its request/traffic counts survive a deadline cancel.
        res.goto = outcome = GotoResolution()
        await resolve_goto(slot.page, getattr(slot, "net", None), tokens, self.s, out=outcome)
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

        # 2) finish: not busy and text length stable for STABLE_S, and every visible
        #    'Show more' / 'Show all' verified as expanded - all within AIO_MAX_WAIT_MS.
        #    Completion is judged from the page's state, never from having clicked.
        end = time.perf_counter() + self.s.aio_max_wait_ms / 1000
        done: set[str] = set()  # expand controls whose click visibly worked
        attempts: dict[str, int] = {}
        problem: dict[str, str] = {}  # why the last click on a control didn't count
        last_len, stable_since = -1, time.perf_counter()
        pending: list[dict] = []
        while time.perf_counter() < end:
            probe = await page.evaluate(AIO_PROBE_JS)
            if not probe["present"]:
                return False, "AI Overview disappeared while loading"
            now = time.perf_counter()
            if probe["len"] != last_len or probe["busy"]:
                last_len, stable_since = probe["len"], now
            elif now - stable_since >= STABLE_S:
                pending = _pending_expanders(probe, done)
                if not pending:
                    return True, "AI Overview complete"
                # 3) expand: click, then wait until the page shows the effect.
                button = pending[0]
                label, bid = button["label"], button["id"]
                if attempts.get(bid, 0) >= MAX_EXPAND_ATTEMPTS:
                    return False, f"could not expand '{label}' after {MAX_EXPAND_ATTEMPTS} attempts ({problem.get(bid, 'no visible change')})"
                attempts[bid] = attempts.get(bid, 0) + 1
                before_url = page.url
                remaining_ms = int((end - time.perf_counter()) * 1000)
                clicked = False
                try:
                    await page.locator(f'[data-serp-btn="{bid}"]').first.click(timeout=max(1, min(CLICK_TIMEOUT_MS, remaining_ms)))
                    clicked = True
                except PlaywrightError as e:
                    problem[bid] = f"click failed: {str(e).splitlines()[0][:120]}"
                    log.warning("could not click '%s' (attempt %d): %s", label, attempts[bid], problem[bid])
                if page.url != before_url:  # also when the click raised part-way
                    return False, f"clicking '{label}' navigated away"
                if clicked:
                    if await self._expansion_verified(page, {**button, "len_before": probe["len"]}, end):
                        done.add(bid)
                        problem.pop(bid, None)
                    else:
                        problem[bid] = "click made no visible change"
                        log.warning("clicking '%s' (attempt %d) made no visible change", label, attempts[bid])
                last_len, stable_since = -1, time.perf_counter()
            await page.wait_for_timeout(100)
        left = ", ".join(f"'{b['label']}' ({problem.get(b['id'], 'not clicked yet')})" for b in pending)
        return False, f"AI Overview not finished within {self.s.aio_max_wait_ms} ms" + (f"; not expanded: {left}" if left else "")

    async def _expansion_verified(self, page: Page, button: dict, end: float) -> bool:
        """Poll until the page shows that clicking `button` expanded something,
        for up to EXPAND_VERIFY_MS (never past `end`)."""
        until = min(end, time.perf_counter() + EXPAND_VERIFY_MS / 1000)
        while True:
            if _expansion_seen(button, await page.evaluate(AIO_PROBE_JS)):
                return True
            if time.perf_counter() >= until:
                return False
            await page.wait_for_timeout(100)

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
