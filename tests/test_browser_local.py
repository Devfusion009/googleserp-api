"""The real browser path against a local stand-in for Google - no network.

BrowserManager + Fetcher + run_serp exactly as in production (resource blocking
on, CDP listener attached), serving a small results page whose links are
/goto?url=<token> and whose /goto answers 302 like Google's. Covers what the
fixture tests can't: the in-page /goto resolution read through CDP while
request routing is active, the hidden-element marking before capture, and
the byte counter. Skipped when no Chromium can be launched (set
BROWSER_EXECUTABLE_PATH if Playwright's own build isn't installed).
"""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.async_api import Error as PlaywrightError

from app.browser import BrowserManager
from app.classify import AioState, Classification
from app.config import Settings
from app.fetcher import Fetcher
from app.models import SerpRequest
from app.orchestrator import run_serp

PAGE = """<!doctype html><html><head><style>.tpl-hidden{display:none}</style></head><body>
<div id="search"><div id="rso">
  <div data-hveid="r1"><div class="N54PNb"><div><a href="/goto?url=TOKEN_R1"><h3>First result</h3></a></div><div>First snippet text.</div></div></div>
  <div data-hveid="r2"><div class="N54PNb"><div><a href="/goto?url=TOKEN_R2"><h3>Second result</h3></a></div><div>Second snippet text.</div></div></div>
</div></div>
<div id="aio">
  <div role="heading" aria-level="2">AI Overview</div>
  <span class="tpl-hidden">An AI Overview is not available for this search</span>
  <span style="display:none">Can't generate an AI overview right now. Try again later.</span>
  <div class="n6owBd">DNS translates human-readable names into the numeric addresses computers use to reach each other on the network.</div>
  <div role="heading" aria-level="3">How it works</div>
  <div class="n6owBd">A resolver asks root, TLD and authoritative servers in turn and caches the answer for later lookups.</div>
  <!--EXPAND-->
  <ul><li class="h7wxwc"><a class="vIWmYe" href="/goto?url=TOKEN_S1"><span class="gpZmoc">Source one</span></a><span class="hxIQcc">Snippet one</span></li>
      <li class="h7wxwc"><a class="vIWmYe" href="/goto?url=TOKEN_S2"><span class="gpZmoc">Source two</span></a><span class="hxIQcc">Snippet two</span></li></ul>
</div>
<img src="/image.png">
</body></html>"""

# "Show more" variants, served for /search?...&v=<name>. The extra section is
# inserted by the click, so it is only parsed if the click really worked.
_MORE = """<div id="more" role="button" style="position:relative;display:inline-block;padding:4px">Show more</div>"""
_REVEAL = """<script>document.getElementById('more').addEventListener('click', e => {
  e.currentTarget.style.display = 'none';
  e.currentTarget.insertAdjacentHTML('afterend', '<div role="heading" aria-level="3">Caching</div>'
    + '<div class="n6owBd">Answers are cached for their time-to-live, so repeated lookups skip the full walk.</div>');
});</script>"""
# A transparent layer over the button: Playwright's click fails ("intercepts pointer events").
_COVER = """<div style="position:absolute;left:0;top:0;width:100vw;height:100vh;z-index:10"></div>"""
EXPAND_VARIANTS = {
    "expands": _MORE + _REVEAL,
    "covered": _MORE + _REVEAL + _COVER,
    "inert": _MORE,
}


def page_for(variant: str | None) -> str:
    return PAGE.replace("<!--EXPAND-->", EXPAND_VARIANTS.get(variant or "", ""))


class FakeGoogle(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    sorry_tokens: set[str] = set()
    image_hits = 0
    # /goto tokens answered without a redirect when the page's own fetch() asks
    # (browsers send Sec-Fetch-Mode; Playwright's request client doesn't): forces the fallback.
    no_redirect_in_page: set[str] = set()
    # /goto tokens whose first request is answered too late (after the page's
    # fetch timeout), like a stalled proxy connection.
    slow_first: set[str] = set()
    slowed: set[str] = set()

    def log_message(self, *a):
        pass

    def _send(self, status, body=b"", headers=()):
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parts = urlsplit(self.path)
        if parts.path == "/goto":
            token = parse_qs(parts.query)["url"][0]
            if token in self.slow_first and token not in self.slowed:
                self.slowed.add(token)
                time.sleep(1.5)
            if token in self.no_redirect_in_page and self.headers.get("Sec-Fetch-Mode"):
                return self._send(200, b"no redirect for you", [("Content-Type", "text/plain")])
            dest = "/sorry/index?continue=x" if token in self.sorry_tokens else f"https://dest.example/{token.lower()}"
            return self._send(302, headers=[("Location", dest)])
        if parts.path == "/search":
            variant = (parse_qs(parts.query).get("v") or [None])[0]
            return self._send(200, page_for(variant).encode(), [("Content-Type", "text/html; charset=utf-8")])
        if parts.path == "/image.png":
            type(self).image_hits += 1
        return self._send(404)


@pytest.fixture
def fake_google():
    FakeGoogle.sorry_tokens = set()
    FakeGoogle.image_hits = 0
    FakeGoogle.no_redirect_in_page, FakeGoogle.slow_first, FakeGoogle.slowed = set(), set(), set()
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeGoogle)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
async def browsers():
    settings = Settings(_env_file=None, headless=True, debug_artifacts=False, aio_max_wait_ms=3000)
    manager = BrowserManager(settings)
    try:
        await manager.start()
    except PlaywrightError as e:
        pytest.skip(f"no launchable Chromium: {str(e).splitlines()[0]}")
    yield settings, manager
    await manager.stop()


async def test_goto_links_resolve_in_page_and_the_page_is_valid(fake_google, browsers):
    settings, manager = browsers
    fetcher = Fetcher(settings, manager)
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns"), fetcher, settings)

    assert out.ok, f"{out.error_code}: {out.error_message}"
    first = out.first
    # the stylesheet-hidden and inline-hidden failure templates don't count
    assert first.classification is Classification.ok and first.aio_state is AioState.complete
    # every /goto link resolved from inside the page (CDP), none through the fallback
    assert first.timings["links_needed"] == first.timings["links_resolved"] == first.timings["links_in_page"] == 4
    assert first.timings["bytes_in"] > len(PAGE) and first.timings["net_requests"] >= 5
    assert FakeGoogle.image_hits == 0  # BLOCK_RESOURCES really blocked the image
    # the 4 /goto resolutions are counted from the network, on top of the page load
    assert first.usage["goto"] == 4
    assert out.requests_used == first.requests_used == 5 and out.usage["goto"] == 4

    page = out.pages[0]
    assert [o.url for o in page.organic] == ["https://dest.example/token_r1", "https://dest.example/token_r2"]
    assert [s.url for s in page.ai_overview.sources] == ["https://dest.example/token_s1", "https://dest.example/token_s2"]
    assert page.ai_overview.intro and page.ai_overview.sections[0].title == "How it works"


async def test_a_goto_answered_with_sorry_is_blocked_captcha(fake_google, browsers):
    settings, manager = browsers
    FakeGoogle.sorry_tokens = {"TOKEN_S2"}
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns"), Fetcher(settings, manager), settings)
    assert not out.ok and out.error_code == "blocked_captcha" and out.status_code == 429


async def test_show_more_that_works_is_clicked_verified_and_parsed(fake_google, browsers):
    settings, manager = browsers
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&v=expands"), Fetcher(settings, manager), settings)
    assert out.ok, f"{out.error_code}: {out.error_message}"
    assert [s.title for s in out.pages[0].ai_overview.sections] == ["How it works", "Caching"]


async def test_show_more_whose_click_fails_is_aio_incomplete(fake_google, browsers):
    # The review's case in a real browser: every click is intercepted by another element.
    settings, manager = browsers
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&v=covered"), Fetcher(settings, manager), settings)
    assert not out.ok and out.error_code == "aio_incomplete", out.error_message
    assert "Show more" in out.error_message and "click failed" in out.error_message


async def test_show_more_that_changes_nothing_is_aio_incomplete(fake_google, browsers):
    settings, manager = browsers
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&v=inert"), Fetcher(settings, manager), settings)
    assert not out.ok and out.error_code == "aio_incomplete", out.error_message
    assert "Show more" in out.error_message and "no visible change" in out.error_message


async def test_fallback_goto_traffic_is_counted_and_marked_partial(fake_google, browsers):
    # Two links can't be resolved in the page, so they go through the request
    # client outside the browser - whose traffic CDP never sees.
    settings, manager = browsers
    FakeGoogle.no_redirect_in_page = {"TOKEN_R2", "TOKEN_S1"}
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns"), Fetcher(settings, manager), settings)
    assert out.ok, f"{out.error_code}: {out.error_message}"
    t, first = out.first.timings, out.first
    assert t["links_in_page"] == 2 and t["links_resolved"] == 4
    assert t["out_of_page_requests"] == 2 and t["bytes_in_partial"] is True
    # each fallback answer is a real 302 with headers: counted, and part of bytes_in
    assert t["bytes_out_of_page"] > 2 * len("HTTP/1.1 302 Found\r\n")
    assert first.usage["goto_fallback"] == 2
    assert out.requests_used == 1 + 4 + 2  # page + 4 in-page /goto (2 without redirect) + 2 fallback
    assert out.pages[0].organic[1].url == "https://dest.example/token_r2"


async def test_a_timed_out_goto_is_retried_in_the_page_and_stays_measured(fake_google, browsers):
    settings, manager = browsers
    settings = settings.model_copy(update={"goto_timeout_ms": 600})
    FakeGoogle.slow_first = {"TOKEN_S2"}
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns"), Fetcher(settings, manager), settings)
    assert out.ok, f"{out.error_code}: {out.error_message}"
    t = out.first.timings
    assert t["links_in_page"] == 4 and "out_of_page_requests" not in t and "bytes_in_partial" not in t
    assert out.first.usage["goto"] == 5  # the timed-out first try is a request too
