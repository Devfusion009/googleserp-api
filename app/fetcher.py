"""Fetch one Google results page with a real browser and wait for the AI Overview.

Never clicks anything that navigates away; only 'Show more' / 'Show all'
buttons (no href) inside the AI Overview block. Once the page is captured, the
/goto result links the response needs are resolved to their destinations
(app/goto_resolver.py) while the page and its proxy session are still open.
"""
import asyncio
import contextlib
import logging
import random
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeout
from selectolax.parser import HTMLParser

from .browser import PagePool, PageSlot, proxy_unreachable
from .classify import HIDDEN_MARK, AioState, Classification, aio_loading, classify_page
from .config import Settings
from .consent import reject_consent
from .goto_resolver import GotoResolution, resolve_goto
from .netwatch import NetworkWatch
from .parsers.registry import goto_tokens_needed

log = logging.getLogger("serp.fetcher")

# Runs in the page. Mirrors classify.find_aio_root so both agree on the block (an AI Overview
# inside a People Also Ask item belongs to that question, not to the query).
_AIO_ROOT_JS = r"""
  const aioRoot = () => {
    const head = [...document.querySelectorAll('h1,h2,[role=heading]')]
      .find(h => (h.textContent || '').trim().toLowerCase() === 'ai overview'
                 && !h.closest('.related-question-pair'));
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
  const shown = el => el.checkVisibility ? el.checkVisibility({visibilityProperty: true}) : el.offsetParent !== null;
  // Only a visible indicator means loading: the block always carries hidden progress bars
  // of its own Copy/Share buttons ("Copy in progress", "Sharing in progress").
  const busy = [...node.querySelectorAll('[aria-busy=true],[role=progressbar]')].some(shown);
  const labelOf = el => (el.innerText || el.getAttribute('aria-label') || '').trim();
  const buttons = [];
  // Google's newer layout puts the AI Overview's own "Show more" outside the block, far up
  // the tree; it is the button whose aria-label names it ("Show more AI Overview").
  const own = /^show (more|all) ai overview$/i;
  const CARD_LINKS = 'a.vIWmYe, a.POYEld';
  // That button goes first: until it is expanded, other controls of the block (the sources'
  // "Show all") are covered and a click on them times out.
  const candidates = new Set([
    ...[...document.querySelectorAll('[role=button][aria-label],button[aria-label]')].filter(b => own.test((b.getAttribute('aria-label') || '').trim())),
    ...node.querySelectorAll('[role=button],button,[data-serp-btn]'),
    ...document.querySelectorAll('[data-serp-btn]')]);
  for (const b of candidates) {
    if (b.closest('a[href]') || b.hasAttribute('href')) continue;
    const label = labelOf(b);
    if (!b.hasAttribute('data-serp-btn')) {
      if (!['show more', 'show all'].includes(label.toLowerCase()) && !own.test((b.getAttribute('aria-label') || '').trim())) continue;
      window.__serpBtnSeq = (window.__serpBtnSeq || 0) + 1;
      b.setAttribute('data-serp-btn', String(window.__serpBtnSeq));
    }
    // A sources 'Show all' reveals cards that are already in the page, hidden: count the
    // hidden cards in the block that are not copies of a visible one. They can sit far from
    // the button (live 2026-10-10: 3 visible cards next to it, the other 4-6 in a hidden
    // list elsewhere in the block), so the whole block is searched.
    let hiddenCards = 0;
    if (/^show all/i.test(label)) {
      const key = a => (a.getAttribute('href') || '') + '|' + (a.getAttribute('aria-label') || '');
      const links = [...node.querySelectorAll(CARD_LINKS)];
      const isShown = a => shown(a.closest('li,[role=listitem]') || a) && shown(a);
      const visible = new Set(links.filter(isShown).map(key));
      hiddenCards = new Set(links.filter(a => !isShown(a)).map(key).filter(k => !visible.has(k))).size;
    }
    buttons.push({id: b.getAttribute('data-serp-btn'), label, visible: shown(b), expanded: b.getAttribute('aria-expanded'), hiddenCards});
  }
  // Answer text the parser reads (intro paragraph, section heading or bullet). The shell
  // Google sends first ("AI Mode reply for ..." over a "Searching" skeleton) has none.
  const answer = !!node.querySelector('.n6owBd, [role=heading][aria-level="3"], li');
  return {present: true, len: text.length, busy, answer, buttons};
}
"""

# A click is retried at most this often, and must show its effect within
# EXPAND_VERIFY_MS (all within AIO_MAX_WAIT_MS).
MAX_EXPAND_ATTEMPTS = 3
EXPAND_VERIFY_MS = 1500
# Google lazy-loads the code behind some AI Overview controls: after "Show more", the
# sources' "Show all" works only once a burst of xjs / search-next scripts has arrived
# (mobile run 2026-10-05: two clicks made no change, the third worked 11 ms after the
# scripts finished). So a click waits, up to SCRIPT_QUIET_MAX_MS, for the page's scripts
# to go quiet (none in flight, none for SCRIPT_IDLE_S), and a click's effect is awaited
# past EXPAND_VERIFY_MS for as long as scripts are still loading - re-clicking then could
# be queued and replayed as a second toggle.
SCRIPT_IDLE_S = 0.5
SCRIPT_QUIET_MAX_MS = 4500  # 2.5 s clicked 'Show all' while its code was still arriving (Polish exits)
# Playwright waits this long for the button to be visible, stable and unobscured
# before a click fails. 1 s was too short on a slow live page (UK run r09: three
# 'Locator.click: Timeout 1000ms exceeded' on a page that had fully loaded), so it
# is a setting (AIO_CLICK_TIMEOUT_MS); the wait stays bounded by AIO_MAX_WAIT_MS.
STABLE_S = 0.3
# Below this many chars of innerText the AIO block is taken for the shell Google
# sends before the answer arrives (heading + "AI Mode reply for ..." is ~40).
AIO_SHELL_CHARS = 200


async def _page_html(page: Page) -> str:
    """page.content(), retried while the page is still navigating (seen live: "Unable to
    retrieve content because the page is navigating and changing the content")."""
    for attempt in range(3):
        try:
            return await page.content()
        except PlaywrightError as e:
            if "navigating" not in str(e) or attempt == 2:
                raise
            await page.wait_for_load_state("domcontentloaded")
    raise AssertionError("unreachable")


def _pending_expanders(probe: dict, done: set[str]) -> list[dict]:
    """Visible 'Show more' / 'Show all' controls not yet expanded. A sources 'Show all'
    whose panel already holds hidden source cards is not pending: what it reveals is in
    the page and the parser reads it (live, its code loaded only seconds after 'Show more'
    and its click could not be confirmed within the budget - the cards were all there)."""
    return [
        b for b in probe["buttons"]
        if b["visible"] and b["label"].lower() in EXPAND_LABELS and b.get("expanded") != "true" and b["id"] not in done
        and not (b["label"].lower() == "show all" and b.get("hiddenCards", 0) > 0)
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
# A `display: contents` element has no box, so checkVisibility() is false for it
# even though its children render; Google's AIO wraps its heading, answer and
# sources in such elements. It counts as shown exactly when its parent is.
MARK_HIDDEN_JS = r"""
(mark) => {""" + _AIO_ROOT_JS + r"""
  const root = aioRoot();
  if (!root || !root.checkVisibility) return 0;
  const shown = el => getComputedStyle(el).display === 'contents'
    ? !el.parentElement || shown(el.parentElement)
    : el.checkVisibility({visibilityProperty: true});
  let n = 0;
  for (const el of root.querySelectorAll('*')) {
    if (!shown(el) && (!el.parentElement || shown(el.parentElement))) { el.setAttribute(mark, ''); n++; }
  }
  return n;
}
"""

# Undoes MARK_HIDDEN_JS: the wait checks the page mid-load, and a mark left on an element
# that is shown later would hide it from the classifier in the final capture.
UNMARK_HIDDEN_JS = r"""
(mark) => { for (const el of document.querySelectorAll('[' + mark + ']')) el.removeAttribute(mark); }
"""


async def _aio_still_loading(page: Page) -> str | None:
    """The classifier's verdict on the page as it is now (aio_loading), with hidden elements
    marked exactly as for the final capture. None if the page can't be read: the wait then
    goes by its own probe, as before."""
    try:
        await page.evaluate(MARK_HIDDEN_JS, HIDDEN_MARK)
        try:
            html = await _page_html(page)
        finally:
            await page.evaluate(UNMARK_HIDDEN_JS, HIDDEN_MARK)
    except PlaywrightError as e:
        log.warning("AI Overview check on the page HTML skipped: %s", str(e).splitlines()[0][:120])
        return None
    return aio_loading(HTMLParser(html))


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
        unreachable_retries = max(0, self.s.proxy_unreachable_retries)
        result = None
        usage: Counter = Counter()
        traffic: Counter = Counter()
        partial = ip_changed = False
        t0 = time.perf_counter()
        attempt = 0
        while True:
            result = await self._fetch_once(url, country, language)
            usage.update(result.usage)
            traffic.update({k: result.timings[k] for k in TRAFFIC_KEYS if k in result.timings})
            partial = partial or bool(result.timings.get("bytes_in_partial"))
            ip_changed = ip_changed or bool(result.session.get("ip_changed"))
            attempt += 1
            result.timings["attempt"] = attempt
            if result.classification not in (Classification.timeout, Classification.network_error):
                break
            if attempt < attempts:
                log.warning("retryable failure %s (attempt %d/%d)", result.classification.value, attempt, attempts)
                continue
            if result.classification is Classification.network_error and unreachable_retries and proxy_unreachable(result.reason):
                lo, hi = sorted(self.s.proxy_unreachable_pause_ms)
                pause_ms = random.randint(lo, hi)
                # Only if a retry still fits the call's deadline; the pause counts in its latency.
                if _ms(t0) + pause_ms < self.s.request_deadline_ms:
                    unreachable_retries -= 1
                    log.warning("proxy unreachable (attempt %d), retrying on the same session in %d ms", attempt, pause_ms)
                    await asyncio.sleep(pause_ms / 1000)
                    continue
            break
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

    def _use_typed_search(self, url: str) -> bool:
        """Typed mode applies to a query's first page only: later pages (a `start` offset)
        are opened by URL, in the session the first page already set up."""
        qs = parse_qs(urlsplit(url).query)
        return self.s.search_mode == "typed" and bool(qs.get("q")) and not qs.get("start")

    @staticmethod
    def _is_results_page(current: str, target: str) -> bool:
        """Is the page on a results page of the host the new search goes to?"""
        cur, tgt = urlsplit(current or ""), urlsplit(target)
        return cur.hostname == tgt.hostname and cur.path == "/search"

    async def _typed_search_on_results(self, page: Page, url: str) -> None:
        """In a session already on a Google results page: replace the query in that page's
        search box and press Enter, as a visitor refining a search. Falls back to the
        homepage path when the box can't be used."""
        query = parse_qs(urlsplit(url).query)["q"][0]
        # The page is left scrolled down by the previous search (AI Overview expanded), and live
        # the box then could not be clicked within 3 s (3 of 7 searches, 2026-10-10): back to the
        # top first, as a visitor would, and if the click still fails, Google's "/" shortcut.
        await page.evaluate("window.scrollTo(0, 0)")
        box = page.locator("textarea[name='q']:visible, input[name='q']:visible").first
        try:
            try:
                await box.click(timeout=2000)
            except PlaywrightError as e:
                log.warning("typed search on results page: box click failed (%s); trying '/'",
                            " | ".join(str(e).splitlines()[:4])[:300])
                await page.keyboard.press("Escape")
                await page.keyboard.press("/")
                if not await page.evaluate("document.activeElement && document.activeElement.name === 'q'"):
                    raise
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
        except PlaywrightError as e:
            log.warning("typed search on results page: box not usable (%s); going through the homepage", str(e).splitlines()[0][:120])
            await self._typed_search(page, url)
            return
        lo, hi = sorted((self.s.typed_key_delay_min_ms, self.s.typed_key_delay_max_ms))
        await page.keyboard.type(query, delay=random.randint(lo, hi))
        await page.wait_for_timeout(random.randint(100, 300))
        before = page.url
        await page.keyboard.press("Enter")
        # "commit", not "domcontentloaded": live, the results HTML had fully arrived but a
        # script stalled on the proxy held DOMContentLoaded back past the timeout (2 of 60 in
        # the 2026-10-10 Poland run). The caller's wait for #search/#rso covers readiness.
        await page.wait_for_url(lambda u: u != before and ("/search?" in u or "/sorry/" in u),
                                wait_until="commit", timeout=self.s.nav_timeout_ms)

    async def _typed_search(self, page: Page, url: str) -> None:
        """Google homepage -> click the search box -> type the query -> Enter. Leaves the page
        on the results navigation; if the homepage is a /sorry/ or consent page, or has no
        search box, it returns without typing and the caller's page classification reports it."""
        parts = urlsplit(url)
        qs = parse_qs(parts.query)
        home_params = {k: qs[k][0] for k in ("hl", "gl") if qs.get(k)}
        home = urlunsplit((parts.scheme, parts.netloc, "/", urlencode(home_params), ""))
        timeout = self.s.nav_timeout_ms
        try:
            await page.goto(home, wait_until="domcontentloaded", timeout=timeout)
        except PlaywrightTimeout:
            # A slow stretch of the proxy (long Poland run: six homepage loads in a row hit the
            # 15 s timeout). One more try on the same session before giving up.
            log.warning("typed search: homepage load timed out; retrying once")
            await page.goto("about:blank")  # cancel the stuck load, or it aborts the retry when it lands
            await page.goto(home, wait_until="domcontentloaded", timeout=timeout)
        if "/sorry/" in page.url or urlsplit(page.url).hostname == "consent.google.com":
            return
        await reject_consent(page)
        lo_w, hi_w = sorted((self.s.typed_warmup_min_ms, self.s.typed_warmup_max_ms))
        if hi_w > 0:
            await page.wait_for_timeout(random.randint(lo_w, hi_w))
        box = page.locator("textarea[name='q'], input[name='q']").first
        try:
            await box.click(timeout=min(timeout, 5000))
        except PlaywrightError as e:
            log.warning("typed search: no search box on %s (%s)", page.url, str(e).splitlines()[0][:120])
            return
        lo, hi = sorted((self.s.typed_key_delay_min_ms, self.s.typed_key_delay_max_ms))
        await page.keyboard.type(qs["q"][0], delay=random.randint(lo, hi))
        await page.wait_for_timeout(random.randint(100, 300))
        await page.keyboard.press("Enter")
        # Results, or Google's CAPTCHA page: a block at the first search redirects to
        # /sorry/index?continue=...search%3F... (encoded), which "/search?" alone never
        # matched - the wait ran to its timeout and the block was reported as a timeout.
        # "commit" for the same reason as in _typed_search_on_results.
        await page.wait_for_url(re.compile(r"/search\?|/sorry/"), wait_until="commit", timeout=timeout)

    async def _run(self, slot: PageSlot, url: str, res: FetchResult, t0: float) -> None:
        page = slot.page
        on_results = (self._use_typed_search(url) and self.s.typed_on_results_page and getattr(slot, "served_results", False)
                      and self._is_results_page(page.url, url))
        mode = "typed-on-results" if on_results else ("typed" if self._use_typed_search(url) else "url")
        log.info("navigate url_sent=%s mode=%s", url, mode)
        if on_results:
            await self._typed_search_on_results(page, url)
        elif self._use_typed_search(url):
            await self._typed_search(page, url)
        else:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.s.nav_timeout_ms)
        res.timings["nav_ms"] = _ms(t0)
        res.final_url = page.url
        if page.url != url:
            log.info("final url differs: %s", page.url)

        early = classify_page(page.url, await _page_html(page))
        if early.classification in (Classification.blocked_captcha, Classification.consent_wall):
            res.classification, res.reason = early.classification, early.reason
            await self._finish(page, res)
            return

        try:
            await page.wait_for_selector("#search, #rso", timeout=self.s.nav_timeout_ms)
        except PlaywrightTimeout:
            res.html = await _page_html(page)
            v = classify_page(page.url, res.html)
            res.classification = v.classification if v.classification is not Classification.ok else Classification.degraded_page
            res.reason = v.reason if v.classification is not Classification.ok else "results container never appeared"
            await self._finish(page, res, capture=False)
            return
        res.timings["results_ms"] = _ms(t0)

        # The result links already on the page are resolved while the AI Overview loads, not
        # after it (live, the two stages took ~1.5 s each one after the other); _resolve_links
        # then does only what appeared later (the overview's source cards).
        prefetch = None
        if self.s.goto_prefetch:
            tokens = goto_tokens_needed(HTMLParser(await _page_html(page)))
            if tokens:
                res.goto = GotoResolution()
                prefetch = asyncio.create_task(resolve_goto(page, getattr(slot, "net", None), tokens, self.s, out=res.goto))
        try:
            await self._settle_and_classify(slot, res, t0, prefetch)
        finally:
            if prefetch is not None and not prefetch.done():
                prefetch.cancel()
                with contextlib.suppress(asyncio.CancelledError, PlaywrightError):
                    await prefetch

    async def _settle_and_classify(self, slot: PageSlot, res: FetchResult, t0: float, prefetch: asyncio.Task | None) -> None:
        page = slot.page
        aio_ok, aio_reason = await self._wait_aio(page, getattr(slot, "net", None))
        res.timings["aio_ms"] = _ms(t0)

        await page.evaluate(MARK_HIDDEN_JS, HIDDEN_MARK)
        res.html = await _page_html(page)
        res.final_url = page.url
        v = classify_page(page.url, res.html)
        res.classification, res.reason, res.aio_state = v.classification, v.reason, v.aio_state
        if v.classification in (Classification.ok, Classification.aio_incomplete, Classification.parse_error):
            slot.served_results = True  # Google served this session a results page
        # The wait's reason says more than the classifier's (what it waited for, how long).
        if not aio_ok and v.classification in (Classification.ok, Classification.aio_incomplete):
            res.classification, res.reason, res.aio_state = Classification.aio_incomplete, aio_reason, AioState.incomplete
        if res.classification is Classification.ok:
            if prefetch is not None:
                with contextlib.suppress(PlaywrightError):
                    await prefetch
            await self._resolve_links(slot, res, t0)
        if res.classification is Classification.ok and self.s.repo_state_file:
            await page.context.storage_state(path=self.s.repo_state_file)
        await self._finish(page, res, capture=False)

    async def _resolve_links(self, slot: PageSlot, res: FetchResult, t0: float) -> None:
        """Resolve the /goto links the response will contain. Unresolved ones are
        left out of res.links; the orchestrator then fails the page as incomplete."""
        tokens = goto_tokens_needed(HTMLParser(res.html or ""))
        res.timings["links_needed"] = len(tokens)
        if not tokens:
            return
        # Created before the call so its request/traffic counts survive a deadline cancel;
        # it already holds what the prefetch during the AI Overview wait resolved.
        if res.goto is None:
            res.goto = GotoResolution()
        outcome = res.goto
        await resolve_goto(slot.page, getattr(slot, "net", None), tokens, self.s, out=outcome)
        res.links = outcome.resolved
        res.timings["links_resolved"] = len(outcome.resolved)
        res.timings["links_in_page"] = outcome.in_page
        res.timings["links_ms"] = _ms(t0)
        if outcome.blocked:
            res.classification = Classification.blocked_captcha
            res.reason = "Google answered a /goto link with its /sorry/ (unusual traffic) page"

    async def _wait_aio(self, page: Page, net: NetworkWatch | None = None) -> tuple[bool, str]:
        """Returns (ok, reason). ok=False only when an AI Overview is present but not finished.

        Google often sends the AIO block as a short shell and fills it from an
        /async/ request (deferred AIO), so with the network watcher the block is
        not settled while such a request is in flight, and a short block is not
        settled until one has finished."""
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
        shell = False
        loading_why: str | None = None  # the classifier's reason, when it disagreed with the probe
        while time.perf_counter() < end:
            probe = await page.evaluate(AIO_PROBE_JS)
            if not probe["present"]:
                return False, "AI Overview disappeared while loading"
            now = time.perf_counter()
            # A shell with no answer text is never settled: it is still loading, whatever
            # the network says (smoke-de q04/q45 were declared complete after ~550 ms on
            # the placeholder, then reported as "0 chars"). A short block that has some
            # answer waits on the network; one with its text settles on stability, as
            # /async/folsrch also runs on pages whose AIO is complete (and without one).
            shell = probe["len"] < AIO_SHELL_CHARS and not probe.get("answer", True)
            loading = shell or (net is not None and probe["len"] < AIO_SHELL_CHARS
                                and (bool(net.async_pending) or not net.async_done))
            if probe["len"] != last_len or probe["busy"] or loading:
                last_len, stable_since = probe["len"], now
            elif now - stable_since >= STABLE_S:
                pending = _pending_expanders(probe, done)
                if not pending:
                    # The probe's answer check is looser than the classifier's: confirm on
                    # the HTML the classifier will read, and keep waiting if it disagrees.
                    loading_why = await _aio_still_loading(page)
                    if loading_why is None:
                        return True, "AI Overview complete"
                    last_len, stable_since = -1, time.perf_counter()
                    await page.wait_for_timeout(100)
                    continue
                # 3) expand: click, then wait until the page shows the effect.
                button = pending[0]
                label, bid = button["label"], button["id"]
                if attempts.get(bid, 0) >= MAX_EXPAND_ATTEMPTS:
                    return False, f"could not expand '{label}' after {MAX_EXPAND_ATTEMPTS} attempts ({problem.get(bid, 'no visible change')})"
                attempts[bid] = attempts.get(bid, 0) + 1
                if done:  # only a control revealed by an earlier expansion waits for lazily loaded code
                    await self._wait_scripts_quiet(page, net, end)
                before_url = page.url
                remaining_ms = int((end - time.perf_counter()) * 1000)
                clicked = False
                try:
                    await page.locator(f'[data-serp-btn="{bid}"]').first.click(timeout=max(1, min(self.s.aio_click_timeout_ms, remaining_ms)))
                    clicked = True
                except PlaywrightError as e:
                    problem[bid] = f"click failed: {str(e).splitlines()[0][:120]}"
                    log.warning("could not click '%s' (attempt %d): %s", label, attempts[bid], problem[bid])
                if page.url != before_url:  # also when the click raised part-way
                    return False, f"clicking '{label}' navigated away"
                if clicked:
                    if await self._expansion_verified(page, {**button, "len_before": probe["len"]}, end, net):
                        done.add(bid)
                        problem.pop(bid, None)
                    else:
                        problem[bid] = "click made no visible change"
                        log.warning("clicking '%s' (attempt %d) made no visible change", label, attempts[bid])
                last_len, stable_since = -1, time.perf_counter()
            await page.wait_for_timeout(100)
        if shell:
            return False, (f"AI Overview still loading after {self.s.aio_max_wait_ms} ms: "
                           "only the 'AI Mode reply' placeholder, no answer text")
        if loading_why is not None and not pending:
            return False, f"AI Overview still loading after {self.s.aio_max_wait_ms} ms: {loading_why}"
        left = ", ".join(f"'{b['label']}' ({problem.get(b['id'], 'not clicked yet')})" for b in pending)
        return False, f"AI Overview not finished within {self.s.aio_max_wait_ms} ms" + (f"; not expanded: {left}" if left else "")

    async def _wait_scripts_quiet(self, page: Page, net: NetworkWatch | None, end: float) -> None:
        """Before a click: let lazily loaded scripts arrive, up to SCRIPT_QUIET_MAX_MS (never past `end`)."""
        if net is None:
            return
        until = min(end, time.perf_counter() + SCRIPT_QUIET_MAX_MS / 1000)
        while not net.scripts_quiet(SCRIPT_IDLE_S) and time.perf_counter() < until:
            await page.wait_for_timeout(100)

    async def _expansion_verified(self, page: Page, button: dict, end: float, net: NetworkWatch | None = None) -> bool:
        """Poll until the page shows that clicking `button` expanded something, for up
        to EXPAND_VERIFY_MS, longer while scripts are still loading (never past `end`)."""
        until = min(end, time.perf_counter() + EXPAND_VERIFY_MS / 1000)
        while True:
            if _expansion_seen(button, await page.evaluate(AIO_PROBE_JS)):
                return True
            now = time.perf_counter()
            if now >= end or (now >= until and (net is None or net.scripts_quiet(SCRIPT_IDLE_S))):
                return False
            await page.wait_for_timeout(100)

    async def _finish(self, page: Page, res: FetchResult, capture: bool = True) -> None:
        if capture or res.html is None:
            res.html = await _page_html(page)
        if self.s.debug_artifacts:
            out = Path(self.s.artifacts_dir) / f"{time.strftime('%Y%m%d_%H%M%S')}_{_slug(res.url_sent)}"
            out.mkdir(parents=True, exist_ok=True)
            (out / "page.html").write_text(res.html or "", encoding="utf-8")
            # A full-page screenshot takes seconds on a results page; the HTML is
            # enough for a page that fetched fine.
            if res.classification is not Classification.ok or self.s.debug_screenshot_on_success:
                try:
                    await page.screenshot(path=str(out / "screenshot.png"), full_page=True, timeout=5000)
                except PlaywrightError as e:
                    log.warning("screenshot failed: %s", str(e).splitlines()[0])
            res.artifact_dir = str(out)
