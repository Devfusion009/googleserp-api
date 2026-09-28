"""Resolve /goto?url=<token> result links through Google's own redirect.

Why a request per link: see app/links.py. GET /goto?url=<token> answers 302 with
the destination in Location; the redirect is not followed, so the destination
site is never contacted. (HEAD doesn't work: it answers 200 without Location.)

1. From the results page itself, with the browser's fetch(redirect: 'manual'):
   same connection (HTTP/2, already open), cookies and proxy session as the
   page, a few KB in total. Scripts can't read an opaque redirect, so the
   Location is read from CDP (app/netwatch.py).
2. Whatever step 1 didn't capture: the browser context's own request client
   (same proxy and cookies, no redirects followed).

A /sorry/ Location means Google flagged the traffic: the page is reported as
blocked_captcha. Nothing is retried on the same session after that.
"""
import asyncio
import logging
from dataclasses import dataclass, field

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from .config import Settings
from .links import destination_from_location, goto_url
from .netwatch import NetworkWatch

log = logging.getLogger("serp.goto")

RESOLVE_IN_PAGE_JS = r"""
async ({urls, limit, timeoutMs}) => {
  let next = 0;
  const one = async (u) => {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), timeoutMs);
    try {
      await fetch(u, {redirect: 'manual', cache: 'no-store', credentials: 'same-origin', signal: ctl.signal});
    } catch (e) {
    } finally {
      clearTimeout(timer);
    }
  };
  const worker = async () => { while (next < urls.length) await one(urls[next++]); };
  await Promise.all(Array.from({length: Math.min(limit, urls.length)}, worker));
}
"""

# CDP events can trail the fetch() promises slightly.
EVENT_SETTLE_POLLS = 10
EVENT_SETTLE_STEP_MS = 20


@dataclass
class GotoResolution:
    resolved: dict[str, str] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    blocked: bool = False
    in_page: int = 0
    fallback: int = 0


async def resolve_goto(page: Page, net: NetworkWatch | None, tokens: list[str], s: Settings) -> GotoResolution:
    out = GotoResolution()
    base = page.url
    urls = {t: goto_url(t, base) for t in tokens}

    def take(token: str, location: str | None) -> None:
        verdict = destination_from_location(location, base)
        if verdict.blocked:
            out.blocked = True
        elif verdict.url:
            out.resolved[token] = verdict.url

    if net is not None and tokens:
        try:
            await page.evaluate(RESOLVE_IN_PAGE_JS, {"urls": list(urls.values()), "limit": s.goto_concurrency, "timeoutMs": s.goto_timeout_ms})
        except PlaywrightError as e:
            log.warning("in-page /goto resolution failed: %s", str(e).splitlines()[0])
        locations: dict[str | None, str | None] = {}
        for _ in range(EVENT_SETTLE_POLLS):
            locations = net.goto_locations()
            if all(t in locations for t in tokens):
                break
            await page.wait_for_timeout(EVENT_SETTLE_STEP_MS)
        for t in tokens:
            if t in locations:
                take(t, locations[t])
        out.in_page = len(out.resolved)

    left = [t for t in tokens if t not in out.resolved]
    if left and not out.blocked:
        gate = asyncio.Semaphore(max(1, s.goto_concurrency))

        async def one(token: str) -> None:
            async with gate:
                try:
                    resp = await page.context.request.get(urls[token], max_redirects=0, timeout=s.goto_timeout_ms)
                except PlaywrightError as e:
                    log.warning("/goto request failed: %s", str(e).splitlines()[0])
                    return
                if 300 <= resp.status < 400:
                    take(token, resp.headers.get("location"))
                else:
                    log.warning("/goto answered %d without a redirect", resp.status)
                await resp.dispose()

        await asyncio.gather(*(one(t) for t in left))
        out.fallback = len(out.resolved) - out.in_page

    out.unresolved = [t for t in tokens if t not in out.resolved]
    log.info("goto tokens=%d resolved=%d (in_page=%d fallback=%d) blocked=%s",
             len(tokens), len(out.resolved), out.in_page, out.fallback, out.blocked)
    return out
