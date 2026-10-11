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
<form action="/search" method="GET"><textarea name="q" aria-label="Search"></textarea></form>
<script>document.querySelector('textarea').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); e.target.form.submit(); } });</script>
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
    # The real block carries hidden progress bars of its Copy/Share buttons.
    "hiddenbusy": '<div role="progressbar" aria-label="Copy in progress" style="display:none"></div>'
                  '<div role="progressbar" aria-label="Sharing in progress" style="visibility:hidden"></div>',
    # Newer layout: the overview's own "Show more" sits outside the block, far up the tree.
    "outside": """<script>(() => { const b = document.createElement('div');
  b.setAttribute('role', 'button'); b.setAttribute('aria-label', 'Show more AI Overview'); b.textContent = 'Show more';
  b.style.cssText = 'display:inline-block;padding:4px';
  b.addEventListener('click', () => { b.style.display = 'none';
    document.querySelector('#aio ul').insertAdjacentHTML('beforebegin', '<div role="heading" aria-level="3">Caching</div>'
      + '<div class="n6owBd">Answers are cached for their time-to-live, so repeated lookups skip the full walk.</div>'); });
  document.body.appendChild(b); })();</script>""",
    # The sources' "Show all" stays covered until the overview's own (outside) "Show more" is
    # expanded, so the outside button has to be clicked first.
    "outside_first": """<div id="cover" style="position:fixed;left:0;top:0;width:100vw;height:100vh;z-index:10"></div>
<div id="all" role="button" style="position:relative;display:inline-block;padding:4px">Show all</div>
<script>document.getElementById('all').addEventListener('click', e => { e.currentTarget.style.display = 'none'; });
(() => { const b = document.createElement('div');
  b.setAttribute('role', 'button'); b.setAttribute('aria-label', 'Show more AI Overview'); b.textContent = 'Show more';
  b.style.cssText = 'position:relative;z-index:20;display:inline-block;padding:4px';
  b.addEventListener('click', () => { b.style.display = 'none'; document.getElementById('cover').remove(); });
  document.body.appendChild(b); })();</script>""",
    "visiblebusy": '<div role="progressbar" aria-label="Generating">...</div>',
    # Like Google after "Show more": the sources' "Show all" works only once a lazily loaded
    # script (served 4.5 s late, about what the mobile run saw) has attached its handler; a click before that does nothing.
    "lazy": _MORE + """<div id="all" role="button" style="display:inline-block;padding:4px">Show all</div>
<script>document.getElementById('more').addEventListener('click', e => {
  e.currentTarget.style.display = 'none';
  const s = document.createElement('script'); s.src = '/lazy.js'; document.body.appendChild(s);
});</script>""",
    "lazy_slow": _MORE + """<div id="all" role="button" style="display:inline-block;padding:4px">Show all</div>
<script>document.getElementById('more').addEventListener('click', e => {
  e.currentTarget.style.display = 'none';
  const s = document.createElement('script'); s.src = '/lazy_slow.js'; document.body.appendChild(s);
});</script>""",
}
LAZY_JS = b"document.getElementById('all').addEventListener('click', e => { e.currentTarget.style.display = 'none'; window.__allClicks = (window.__allClicks || 0) + 1; });"


# Google's newer AIO layout wraps the heading, the answer and the source list in
# `display: contents` elements (inline style or stylesheet). They draw no box of
# their own, so checkVisibility() is false for them although their content shows.
# The failure template inside the heading wrapper must still count as hidden.
CONTENTS_PAGE = (
    PAGE.replace("<style>", "<style>.dc{display:contents}")
    .replace('<div role="heading" aria-level="2">AI Overview</div>\n  <span class="tpl-hidden">An AI Overview is not available for this search</span>',
             '<div style="display:contents"><div role="heading" aria-level="2">AI Overview</div>\n'
             '  <span class="tpl-hidden">An AI Overview is not available for this search</span></div>')
    .replace('<div class="n6owBd">DNS translates', '<div style="display: contents"><div class="n6owBd">DNS translates')
    .replace("the network.</div>", "the network.</div></div>")
    .replace('<div role="heading" aria-level="3">How it works</div>', '<div class="dc"><div role="heading" aria-level="3">How it works</div>')
    .replace("later lookups.</div>", "later lookups.</div></div>")
    .replace("<ul>", '<div class="dc"><ul>').replace("</ul>", "</ul></div>")
)


# Something over the results page's search box that takes the clicks, and Google's "/"
# shortcut, which focuses the box.
COVERED_BOX = """<div style="position:fixed;inset:0;z-index:50"></div>
<script>document.addEventListener('keydown', e => { if (e.key === '/' && document.activeElement.name !== 'q') {
  e.preventDefault(); document.querySelector("textarea[name='q']").focus(); } });</script>"""


# Google's homepage reduced to what the typed search needs: a form with a q box.
HOME = """<!doctype html><html><body><form action="/search" method="GET">
<textarea name="q" aria-label="Search"></textarea><input type="submit" value="Search"></form>
<script>/* like Google's box: Enter submits the form instead of adding a new line */
document.querySelector('textarea').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); e.target.form.submit(); } });
</script></body></html>"""


# Like Google's consent dialog on UK/EU exits: covers the page until "Reject all" is pressed
CONSENT_OVERLAY = """<div id="consent" style="position:fixed;inset:0;background:#fff;z-index:9"><h1>Before you continue to Google</h1>
<button>Accept all</button><button onclick="document.getElementById('consent').remove()">Reject all</button></div>"""
CONSENT_OVERLAY_PL = """<div id="consent" style="position:fixed;inset:0;background:#fff;z-index:9"><h1>Zanim przejdziesz do Google</h1>
<button>Zaakceptuj wszystko</button><button onclick="document.getElementById('consent').remove()">Odrzuć wszystko</button></div>"""


def _shell_page(fill_after_ms: int | None) -> str:
    """The AI Overview as Google first sends it: the heading over an 'AI Mode reply for ...'
    placeholder, no answer text. With fill_after_ms the answer replaces it that much later."""
    start = PAGE.index('  <span class="tpl-hidden">')
    end = PAGE.index("</ul>") + len("</ul>")
    answer = PAGE[start:end].replace("<!--EXPAND-->", "")
    fill = "" if fill_after_ms is None else (
        f"<script>setTimeout(() => {{ const t = document.getElementById('answer');"
        f" document.getElementById('shell').replaceWith(t.content.cloneNode(true)); }}, {fill_after_ms});</script>")
    return (PAGE[:start] + '<div id="shell"><span>AI Mode reply for dns</span></div>'
            + f'<template id="answer">{answer}</template>{fill}' + PAGE[end:])


def _sources_show_all(hidden_card: bool) -> str:
    """The sources panel with an inert 'Show all' (its click does nothing, as when its code has
    not loaded yet) and, optionally, a third card already in the page but hidden."""
    third = ('<li class="h7wxwc" style="display:none"><a class="vIWmYe" href="/goto?url=TOKEN_S3"><span class="gpZmoc">Source three</span></a>'
             '<span class="hxIQcc">Snippet three</span></li>') if hidden_card else ""
    return (PAGE.replace("</ul>", third + "</ul>", 1)
            .replace("</ul>", '</ul><div id="all" role="button" style="display:inline-block;padding:4px">Show all</div>', 1)
            .replace("<!--EXPAND-->", ""))


def _sources_show_all_far(extra_card: bool) -> str:
    """Live layout 2026-10-10: the visible cards sit with 'Show all' (inert here), and the full
    list is a hidden copy elsewhere in the block - with a card not shown, or only copies."""
    card = '<li class="h7wxwc"><a class="vIWmYe" href="/goto?url={t}"><span class="gpZmoc">{n}</span></a><span class="hxIQcc">x</span></li>'
    hidden = card.format(t="TOKEN_S1", n="Source one") + card.format(t="TOKEN_S2", n="Source two")
    if extra_card:
        hidden += card.format(t="TOKEN_S3", n="Source three")
    start = PAGE.index("<ul>")
    end = PAGE.index("</ul>") + len("</ul>")
    return (PAGE[:start] + '<div><div>' + PAGE[start:end]
            + '<div id="all" role="button" style="display:inline-block;padding:4px">Show all</div></div></div>'
            + f'<div style="display:none"><ul>{hidden}</ul></div>' + PAGE[end:]).replace("<!--EXPAND-->", "")


def page_for(variant: str | None) -> str:
    if variant == "cached_js":
        return PAGE.replace("<!--EXPAND-->", '<script src="/app.js"></script>')
    if variant == "showall_far_hidden_cards":
        return _sources_show_all_far(True)
    if variant == "showall_far_copies_only":
        return _sources_show_all_far(False)
    if variant == "contents":
        return CONTENTS_PAGE
    if variant == "showall_hidden_cards":
        return _sources_show_all(True)
    if variant == "showall_no_hidden_cards":
        return _sources_show_all(False)
    if variant == "shell_late":
        return _shell_page(1200)
    if variant == "shell":
        return _shell_page(None)
    return PAGE.replace("<!--EXPAND-->", EXPAND_VARIANTS.get(variant or "", ""))


class FakeGoogle(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    sorry_tokens: set[str] = set()
    image_hits = 0
    ip_hits = 0
    home_hits = 0
    consent_on_home = False
    search_queries: list = []
    # /goto tokens answered without a redirect when the page's own fetch() asks
    # (browsers send Sec-Fetch-Mode; Playwright's request client doesn't): forces the fallback.
    no_redirect_in_page: set[str] = set()
    # /goto tokens whose first request is answered too late (after the page's
    # fetch timeout), like a stalled proxy connection.
    slow_first: set[str] = set()
    # /goto tokens whose first request from outside the page (no Sec-Fetch-Mode) is answered late
    slow_fallback: set[str] = set()
    slow_home_once = False
    slowed: set[str] = set()
    app_js_hits = 0
    cover_box = False
    goto_times: list[float] = []
    lazy_js_served: float | None = None

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
            type(self).goto_times.append(time.monotonic())
            if token in self.slow_first and token not in self.slowed:
                self.slowed.add(token)
                time.sleep(1.5)
            if token in self.slow_fallback and not self.headers.get("Sec-Fetch-Mode"):
                type(self).slow_fallback = self.slow_fallback - {token}
                time.sleep(1.5)
            if token in self.no_redirect_in_page and self.headers.get("Sec-Fetch-Mode"):
                return self._send(200, b"no redirect for you", [("Content-Type", "text/plain")])
            dest = "/sorry/index?continue=x" if token in self.sorry_tokens else f"https://dest.example/{token.lower()}"
            return self._send(302, headers=[("Location", dest)])
        if parts.path == "/search" and (parse_qs(parts.query).get("q") or [""])[0] == "blockme":
            # like Google blocking at the first search: 302 to /sorry/ with the search URL encoded
            return self._send(302, headers=[("Location", "/sorry/index?continue=https://www.google.com/search%3Fq%3Dblockme")])
        if parts.path == "/sorry/index":
            body = b"<html><body>Our systems have detected unusual traffic from your computer network.</body></html>"
            return self._send(429, body, [("Content-Type", "text/html")])
        if parts.path == "/search":
            type(self).search_queries.append((parse_qs(parts.query).get("q") or [None])[0])
            variant = (parse_qs(parts.query).get("v") or [None])[0]
            body = page_for(variant)
            if self.cover_box:
                body = body.replace("</body>", COVERED_BOX + "</body>")
            return self._send(200, body.encode(), [("Content-Type", "text/html; charset=utf-8")])
        if parts.path == "/":
            type(self).home_hits += 1
            if self.slow_home_once:
                type(self).slow_home_once = False
                time.sleep(2.5)
            overlay = CONSENT_OVERLAY_PL if self.consent_on_home == "pl" else CONSENT_OVERLAY
            home = HOME.replace("</body>", overlay + "</body>") if self.consent_on_home else HOME
            return self._send(200, home.encode(), [("Content-Type", "text/html; charset=utf-8")])
        if parts.path == "/ipjson":  # like https://ipinfo.io/json
            body = b'{"ip": "203.0.113.7", "city": "Chicago", "timezone": "America/Chicago"}'
            return self._send(200, body, [("Content-Type", "application/json")])
        if parts.path == "/ip":
            type(self).ip_hits += 1
            return self._send(200, b"203.0.113.7", [("Content-Type", "text/plain")])
        if parts.path in ("/lazy.js", "/lazy_slow.js"):
            # 4.5 s: longer than three 1.5 s click checks; 7.5 s: the slowest Polish-exit pages
            time.sleep(7.5 if parts.path == "/lazy_slow.js" else 4.5)
            type(self).lazy_js_served = time.monotonic()
            return self._send(200, LAZY_JS, [("Content-Type", "text/javascript")])
        if parts.path == "/app.js":  # cacheable, like Google's xjs bundles
            type(self).app_js_hits += 1
            return self._send(200, b"window.__app = 1;", [("Content-Type", "text/javascript"), ("Cache-Control", "public, max-age=3600")])
        if parts.path == "/image.png":
            type(self).image_hits += 1
        return self._send(404)


@pytest.fixture
def fake_google():
    FakeGoogle.sorry_tokens = set()
    FakeGoogle.image_hits = 0
    FakeGoogle.ip_hits = 0
    FakeGoogle.home_hits = 0
    FakeGoogle.consent_on_home = False
    FakeGoogle.search_queries = []
    FakeGoogle.no_redirect_in_page, FakeGoogle.slow_first, FakeGoogle.slowed = set(), set(), set()
    FakeGoogle.slow_fallback, FakeGoogle.slow_home_once = set(), False
    FakeGoogle.app_js_hits, FakeGoogle.goto_times, FakeGoogle.lazy_js_served = 0, [], None
    FakeGoogle.cover_box = False
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


async def test_blocking_images_keeps_the_http_cache(fake_google, browsers):
    # Playwright's request routing would turn the cache off and refetch the script every search.
    settings, manager = browsers
    fetcher = Fetcher(settings, manager)
    for _ in range(2):
        out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&v=cached_js"), fetcher, settings)
        assert out.ok, f"{out.error_code}: {out.error_message}"
    assert FakeGoogle.app_js_hits == 1 and FakeGoogle.image_hits == 0
    assert out.requests_used == 5  # the cached script is not a network request


async def test_result_links_resolve_while_the_aio_is_still_loading(fake_google, browsers):
    settings, manager = browsers
    settings.aio_max_wait_ms = Settings(_env_file=None).aio_max_wait_ms
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&v=lazy_slow"), Fetcher(settings, manager), settings)
    assert out.ok, f"{out.error_code}: {out.error_message}"
    assert FakeGoogle.goto_times and FakeGoogle.lazy_js_served and max(FakeGoogle.goto_times) < FakeGoogle.lazy_js_served
    # resolved once each, all in the page, though in two passes
    assert out.first.timings["links_resolved"] == out.first.timings["links_in_page"] == 4 and out.first.usage["goto"] == 4


async def test_display_contents_wrappers_do_not_hide_the_aio(fake_google, browsers):
    settings, manager = browsers
    assert CONTENTS_PAGE.count('class="dc"') == 2 and CONTENTS_PAGE.count("display:contents") == 2  # the page really changed
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&v=contents"), Fetcher(settings, manager), settings)
    assert out.ok, f"{out.error_code}: {out.error_message}"
    assert out.first.aio_state is AioState.complete
    aio = out.pages[0].ai_overview
    assert aio.intro and aio.sections[0].title == "How it works"
    assert [s.url for s in aio.sources] == ["https://dest.example/token_s1", "https://dest.example/token_s2"]


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


async def test_the_overviews_own_show_more_outside_the_block_is_clicked(fake_google, browsers):
    settings, manager = browsers
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&v=outside"), Fetcher(settings, manager), settings)
    assert out.ok, f"{out.error_code}: {out.error_message}"
    assert [s.title for s in out.pages[0].ai_overview.sections] == ["How it works", "Caching"]


async def test_the_overviews_own_show_more_is_clicked_before_the_controls_it_covers(fake_google, browsers):
    settings, manager = browsers
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&v=outside_first"), Fetcher(settings, manager), settings)
    assert out.ok, f"{out.error_code}: {out.error_message}"


async def test_hidden_progress_bars_in_the_overview_do_not_keep_it_loading(fake_google, browsers):
    settings, manager = browsers
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&v=hiddenbusy"), Fetcher(settings, manager), settings)
    assert out.ok, f"{out.error_code}: {out.error_message}"


async def test_a_visible_progress_bar_keeps_the_overview_loading(fake_google, browsers):
    settings, manager = browsers
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&v=visiblebusy"), Fetcher(settings, manager), settings)
    assert not out.ok and out.error_code == "aio_incomplete" and "not finished" in out.error_message, out.error_message


async def test_a_placeholder_shell_is_waited_for_until_the_answer_arrives(fake_google, browsers):
    # smoke-de q04/q45: the shell was taken as finished after ~550 ms.
    settings, manager = browsers
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&v=shell_late"), Fetcher(settings, manager), settings)
    assert out.ok, f"{out.error_code}: {out.error_message}"
    assert [s.title for s in out.pages[0].ai_overview.sections] == ["How it works"]


async def test_a_placeholder_shell_that_never_fills_is_reported_as_still_loading(fake_google, browsers):
    settings, manager = browsers
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&v=shell"), Fetcher(settings, manager), settings)
    assert not out.ok and out.error_code == "aio_incomplete"
    assert "still loading after 3000 ms" in out.error_message, out.error_message


async def test_a_control_whose_code_loads_late_is_clicked_once_it_has_loaded(fake_google, browsers):
    # Mobile run 2026-10-05: "Show all" clicked before its script arrived made no change twice.
    settings, manager = browsers
    settings.aio_max_wait_ms = 8000
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&v=lazy"), Fetcher(settings, manager), settings)
    assert out.ok, f"{out.error_code}: {out.error_message}"


async def test_a_control_whose_code_takes_7_s_to_load_is_expanded_within_the_default_budget(fake_google, browsers):
    # Poland run 2026-10-07: 'Show all' code arrived ~5 s after 'Show more'; the old 8 s budget
    # (and 2.5 s pre-click wait) ran out after one unconfirmed click.
    settings, manager = browsers
    settings.aio_max_wait_ms = Settings(_env_file=None).aio_max_wait_ms
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&v=lazy_slow"), Fetcher(settings, manager), settings)
    assert out.ok, f"{out.error_code}: {out.error_message}"


async def test_a_show_all_whose_hidden_cards_are_in_the_page_is_complete_without_a_click(fake_google, browsers):
    settings, manager = browsers
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&v=showall_hidden_cards"), Fetcher(settings, manager), settings)
    assert out.ok, f"{out.error_code}: {out.error_message}"
    assert [s.title for s in out.pages[0].ai_overview.sources] == ["Source one", "Source two", "Source three"]


async def test_a_show_all_with_nothing_hidden_behind_it_must_still_be_expanded(fake_google, browsers):
    settings, manager = browsers
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&v=showall_no_hidden_cards"), Fetcher(settings, manager), settings)
    assert not out.ok and out.error_code == "aio_incomplete" and "Show all" in out.error_message, out.error_message


async def test_hidden_cards_far_from_show_all_still_count(fake_google, browsers):
    settings, manager = browsers
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&v=showall_far_hidden_cards"), Fetcher(settings, manager), settings)
    assert out.ok, f"{out.error_code}: {out.error_message}"
    assert [s.title for s in out.pages[0].ai_overview.sources] == ["Source one", "Source two", "Source three"]


async def test_hidden_copies_of_visible_cards_do_not_excuse_show_all(fake_google, browsers):
    settings, manager = browsers
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&v=showall_far_copies_only"), Fetcher(settings, manager), settings)
    assert not out.ok and out.error_code == "aio_incomplete" and "Show all" in out.error_message, out.error_message


async def test_a_fallback_goto_lookup_that_times_out_is_retried(fake_google, browsers):
    settings, manager = browsers
    settings.goto_timeout_ms = 1000
    FakeGoogle.no_redirect_in_page = {"TOKEN_S2"}  # forces the fallback for this link
    FakeGoogle.slow_fallback = {"TOKEN_S2"}  # whose first fallback request is answered after 1.5 s
    out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns"), Fetcher(settings, manager), settings)
    assert out.ok, f"{out.error_code}: {out.error_message}"
    assert out.first.usage["goto_fallback"] == 2  # the timed-out try and the retry, both counted


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


# --- latency: prewarmed slot, exit-IP checks, screenshots -----------------------

async def _manager(**overrides):
    settings = Settings(_env_file=None, headless=True, aio_max_wait_ms=3000, **overrides)
    manager = BrowserManager(settings)
    try:
        await manager.start()
    except PlaywrightError as e:
        pytest.skip(f"no launchable Chromium: {str(e).splitlines()[0]}")
    return settings, manager


async def test_prewarm_builds_the_slot_and_a_recent_ip_check_is_not_repeated(fake_google):
    settings, manager = await _manager(exit_ip_check_url=f"{fake_google}/ip", debug_artifacts=False)
    try:
        assert FakeGoogle.ip_hits == 1  # the slot was built (and its IP checked) at startup
        fetcher = Fetcher(settings, manager)
        for _ in range(2):
            out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns"), fetcher, settings)
            assert out.ok, f"{out.error_code}: {out.error_message}"
        # each request checks once, after it; the check before is skipped (checked < 60 s ago)
        assert FakeGoogle.ip_hits == 3
    finally:
        await manager.stop()


async def test_recheck_zero_checks_before_every_request(fake_google):
    settings, manager = await _manager(exit_ip_check_url=f"{fake_google}/ip", exit_ip_recheck_seconds=0, debug_artifacts=False)
    try:
        await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns"), Fetcher(settings, manager), settings)
        assert FakeGoogle.ip_hits == 3  # startup + before + after
    finally:
        await manager.stop()


async def test_the_page_reports_the_exit_ips_timezone_not_the_hosts(fake_google):
    # Mobile run: US exit IPs, but every page said Asia/Kolkata (the host's timezone).
    settings, manager = await _manager(exit_ip_check_url=f"{fake_google}/ipjson", debug_artifacts=False)
    try:
        async with manager.page("US", "en") as slot:
            await slot.page.goto(f"{fake_google}/")
            tz = await slot.page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone")
            offset = await slot.page.evaluate("new Date(2026, 0, 15).getTimezoneOffset()")
        assert tz == "America/Chicago" and offset == 360  # CST, UTC-6
        assert slot.report["timezone"] == "America/Chicago"
    finally:
        await manager.stop()


async def test_screenshot_only_for_a_failed_page(fake_google, tmp_path):
    settings, manager = await _manager(debug_artifacts=True, artifacts_dir=str(tmp_path))
    try:
        fetcher = Fetcher(settings, manager)
        ok = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns"), fetcher, settings)
        assert ok.ok
        ok_dir = tmp_path / ok.first.artifact_dir.split("/")[-1]
        assert (ok_dir / "page.html").exists() and not (ok_dir / "screenshot.png").exists()
        FakeGoogle.sorry_tokens = {"TOKEN_S2"}
        bad = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dnss"), fetcher, settings)
        assert bad.error_code == "blocked_captcha"
        assert (tmp_path / bad.first.artifact_dir.split("/")[-1] / "screenshot.png").exists()
    finally:
        await manager.stop()


# --- typed search (SEARCH_MODE=typed): homepage -> type the query -> Enter ------

async def test_typed_search_opens_the_homepage_types_the_query_and_returns_the_same_result(fake_google):
    settings, manager = await _manager(search_mode="typed", typed_key_delay_min_ms=1, typed_key_delay_max_ms=2, debug_artifacts=False)
    try:
        out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&gl=us&hl=en"), Fetcher(settings, manager), settings)
        assert out.ok, f"{out.error_code}: {out.error_message}"
        assert FakeGoogle.home_hits == 1  # the homepage was opened first
        assert FakeGoogle.search_queries == ["dns"]  # and the query reached /search by typing + Enter
        assert [o.url for o in out.pages[0].organic] == ["https://dest.example/token_r1", "https://dest.example/token_r2"]
        assert out.pages[0].ai_overview.sections[0].title == "How it works"
    finally:
        await manager.stop()


async def test_a_homepage_that_times_out_once_is_loaded_again(fake_google):
    FakeGoogle.slow_home_once = True
    settings, manager = await _manager(search_mode="typed", typed_key_delay_min_ms=1, typed_key_delay_max_ms=2,
                                       nav_timeout_ms=2000, debug_artifacts=False)
    try:
        out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&gl=us&hl=en"), Fetcher(settings, manager), settings)
        assert out.ok, f"{out.error_code}: {out.error_message}"
        assert FakeGoogle.home_hits == 2
    finally:
        await manager.stop()


async def test_a_session_already_served_results_types_the_next_query_on_the_results_page(fake_google):
    settings, manager = await _manager(search_mode="typed", typed_key_delay_min_ms=1, typed_key_delay_max_ms=2,
                                       typed_warmup_min_ms=800, typed_warmup_max_ms=800, debug_artifacts=False)
    try:
        fetcher = Fetcher(settings, manager)
        first = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&gl=us&hl=en"), fetcher, settings)
        second = await run_serp(SerpRequest(url=f"{fake_google}/search?q=caching&gl=us&hl=en"), fetcher, settings)
        assert first.ok and second.ok, f"{second.error_code}: {second.error_message}"
        assert FakeGoogle.home_hits == 1  # the second search did not go back to the homepage
        assert FakeGoogle.search_queries == ["dns", "caching"]
        assert second.first.timings["nav_ms"] < first.first.timings["nav_ms"]  # no homepage, no pause
    finally:
        await manager.stop()


async def test_a_covered_search_box_on_the_results_page_is_reached_with_the_slash_shortcut(fake_google):
    FakeGoogle.cover_box = True
    settings, manager = await _manager(search_mode="typed", typed_key_delay_min_ms=1, typed_key_delay_max_ms=2, debug_artifacts=False)
    try:
        fetcher = Fetcher(settings, manager)
        for q in ("dns", "caching"):
            out = await run_serp(SerpRequest(url=f"{fake_google}/search?q={q}&gl=us&hl=en"), fetcher, settings)
            assert out.ok, f"{out.error_code}: {out.error_message}"
        assert FakeGoogle.home_hits == 1 and FakeGoogle.search_queries == ["dns", "caching"]
    finally:
        await manager.stop()


async def test_the_results_page_fast_path_can_be_turned_off(fake_google):
    settings, manager = await _manager(search_mode="typed", typed_key_delay_min_ms=1, typed_key_delay_max_ms=2,
                                       typed_on_results_page=False, debug_artifacts=False)
    try:
        fetcher = Fetcher(settings, manager)
        for q in ("dns", "caching"):
            assert (await run_serp(SerpRequest(url=f"{fake_google}/search?q={q}&gl=us&hl=en"), fetcher, settings)).ok
        assert FakeGoogle.home_hits == 2
    finally:
        await manager.stop()


async def test_a_new_session_opens_the_warm_up_pages_before_its_first_search(fake_google):
    settings, manager = await _manager(warmup_urls=f"{fake_google}/ip, {fake_google}/", warmup_dwell_min_ms=10, warmup_dwell_max_ms=20,
                                       debug_artifacts=False)
    try:
        assert FakeGoogle.ip_hits == 1 and FakeGoogle.home_hits == 1  # opened at startup (prewarm), before any request
        out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns"), Fetcher(settings, manager), settings)
        assert out.ok
    finally:
        await manager.stop()


async def test_warm_up_answers_the_consent_dialog(fake_google):
    FakeGoogle.consent_on_home = "pl"
    settings, manager = await _manager(warmup_urls=f"{fake_google}/", warmup_dwell_min_ms=10, warmup_dwell_max_ms=20,
                                       debug_artifacts=False)
    try:
        slot = manager._slots.get_nowait()
        assert FakeGoogle.home_hits == 1 and await slot.page.locator("#consent").count() == 0  # "Odrzuć wszystko" pressed
        manager._slots.put_nowait(slot)
    finally:
        await manager.stop()


async def test_the_exit_ip_check_after_a_request_can_be_turned_off(fake_google):
    settings, manager = await _manager(exit_ip_check_url=f"{fake_google}/ip", exit_ip_check_after=False, debug_artifacts=False)
    try:
        assert (await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns"), Fetcher(settings, manager), settings)).ok
        assert FakeGoogle.ip_hits == 1  # only the check when the session was built
    finally:
        await manager.stop()


async def test_typed_search_rejects_the_polish_consent_dialog(fake_google):
    FakeGoogle.consent_on_home = "pl"
    settings, manager = await _manager(search_mode="typed", typed_key_delay_min_ms=1, typed_key_delay_max_ms=2, debug_artifacts=False)
    try:
        out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&gl=us&hl=en"), Fetcher(settings, manager), settings)
        assert out.ok, f"{out.error_code}: {out.error_message}"
        assert FakeGoogle.search_queries == ["dns"]
    finally:
        await manager.stop()


async def test_typed_search_pauses_on_the_homepage_before_typing(fake_google):
    settings, manager = await _manager(search_mode="typed", typed_key_delay_min_ms=1, typed_key_delay_max_ms=2,
                                       typed_warmup_min_ms=1200, typed_warmup_max_ms=1200, debug_artifacts=False)
    try:
        out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&gl=us&hl=en"), Fetcher(settings, manager), settings)
        assert out.ok, f"{out.error_code}: {out.error_message}"
        assert out.first.timings["nav_ms"] >= 1200
    finally:
        await manager.stop()


async def test_typed_search_blocked_at_the_first_search_is_a_captcha_not_a_timeout(fake_google):
    # Live (session run 2026-10-07): the redirect to /sorry/ never matched the "/search?" wait,
    # so the block came back after the 15 s navigation timeout, classified as a timeout.
    settings, manager = await _manager(search_mode="typed", typed_key_delay_min_ms=1, typed_key_delay_max_ms=2, debug_artifacts=False)
    try:
        out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=blockme&gl=us&hl=en"), Fetcher(settings, manager), settings)
        assert out.error_code == "blocked_captcha", f"{out.error_code}: {out.error_message}"
        assert out.first.timings["nav_ms"] < 5000
    finally:
        await manager.stop()


async def test_typed_search_rejects_the_consent_dialog_that_covers_the_homepage(fake_google):
    FakeGoogle.consent_on_home = True
    settings, manager = await _manager(search_mode="typed", typed_key_delay_min_ms=1, typed_key_delay_max_ms=2, debug_artifacts=False)
    try:
        out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns&gl=us&hl=en"), Fetcher(settings, manager), settings)
        assert out.ok, f"{out.error_code}: {out.error_message}"
        assert FakeGoogle.search_queries == ["dns"]
    finally:
        await manager.stop()


async def test_repo_fingerprint_patches_apply_and_state_file_is_saved_then_reused(fake_google, tmp_path):
    state = tmp_path / "state.json"
    settings, manager = await _manager(repo_fingerprint=True, repo_state_file=str(state), debug_artifacts=False)
    try:
        out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns"), Fetcher(settings, manager), settings)
        assert out.ok, f"{out.error_code}: {out.error_message}"
        assert state.exists() and '"cookies"' in state.read_text()
    finally:
        await manager.stop()


async def test_url_mode_does_not_open_the_homepage(fake_google):
    settings, manager = await _manager(debug_artifacts=False)
    try:
        out = await run_serp(SerpRequest(url=f"{fake_google}/search?q=dns"), Fetcher(settings, manager), settings)
        assert out.ok and FakeGoogle.home_hits == 0
    finally:
        await manager.stop()


def test_typed_mode_applies_to_a_querys_first_page_only():
    f = Fetcher(Settings(_env_file=None, search_mode="typed"), browsers=None)
    assert f._use_typed_search("https://www.google.com/search?q=dns&gl=us&hl=en")
    assert not f._use_typed_search("https://www.google.com/search?q=dns&start=10")  # page 2: by URL
    assert not f._use_typed_search("https://www.google.com/search?gl=us")  # no query to type
    assert not Fetcher(Settings(_env_file=None), browsers=None)._use_typed_search("https://www.google.com/search?q=dns")
