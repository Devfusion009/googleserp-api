"""Classification + parsing together, on the 16 real saved pages.

Each fixture goes through what a live request does after the browser has the
page: classify_page() on the HTML, the fetcher's /goto step (tokens the parsers
need -> a resolver), then run_serp() - parsers, completeness gate, error codes.
Only the browser and Google's redirect are replaced: `resolve` stands in for
Google's /goto answers.
"""
import json
import re
from pathlib import Path
from typing import Callable

import pytest
from selectolax.parser import HTMLParser

from app.classify import AioState, Classification, classify_page
from app.config import Settings
from app.fetcher import FetchResult
from app.models import SerpRequest
from app.orchestrator import run_serp
from app.parsers.registry import _organic, _paid, goto_tokens_needed

FIXTURES = Path(__file__).parent / "fixtures"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text())

HAS_AIO = {
    "t_mobile", "mobile", "apple", "best_cell_phone_plans", "car_insurance_quotes",
    "crm_software", "how_does_dns_work", "why_is_the_sky_blue", "best_supplements_for_sleep",
    "how_to_replace_a_kitchen_faucet_cartridge_delta_1400_series",
    "difficult_flights_to_brussels_from_shanghai",
}
# Pages whose result links Google served as /goto?url=<token> (the rest have direct hrefs).
GOTO_PAGES = {"apple", "best_cell_phone_plans", "chase_bank_login", "mobile", "t_mobile", "wikipedia"}
DIRECT_PAGES = set(MANIFEST) - GOTO_PAGES

Resolver = Callable[[list[str]], dict[str, str]]


def resolve_none(tokens: list[str]) -> dict[str, str]:
    return {}


def resolve_all(tokens: list[str]) -> dict[str, str]:
    return {t: f"https://resolved.test/{i}" for i, t in enumerate(tokens)}


def html_of(slug: str) -> str:
    return (FIXTURES / f"{slug}.html").read_text(encoding="utf-8")


class FixtureFetcher:
    """Fetcher.fetch() for a saved page: the real classifier and /goto token
    collection, with `resolve` in place of Google's redirect."""

    def __init__(self, html: str, resolve: Resolver = resolve_none):
        self.html, self.resolve = html, resolve

    async def fetch(self, url, country, language) -> FetchResult:
        v = classify_page(url, self.html)
        r = FetchResult(url_sent=url, final_url=url, html=self.html, classification=v.classification, reason=v.reason, aio_state=v.aio_state)
        r.timings = {"attempt": 1}
        if v.classification is Classification.ok:
            r.links = self.resolve(goto_tokens_needed(HTMLParser(self.html)))
        return r


async def run(slug: str, resolve: Resolver = resolve_none):
    url = MANIFEST[slug]["url"]
    return await run_serp(SerpRequest(url=url), FixtureFetcher(html_of(slug), resolve), Settings(_env_file=None))


# --- classification alone ------------------------------------------------------

@pytest.mark.parametrize("slug", sorted(MANIFEST))
def test_every_real_page_classifies_ok_with_the_right_aio_state(slug):
    v = classify_page(MANIFEST[slug]["url"], html_of(slug))
    assert v.classification is Classification.ok, f"{slug}: {v.reason}"
    assert v.aio_state is (AioState.complete if slug in HAS_AIO else AioState.absent)


def test_hidden_failure_templates_do_not_fail_a_real_aio():
    # The DNS page carries "An AI Overview is not available for this search" and
    # "Can't generate an AI overview right now" in display:none spans.
    html = html_of("how_does_dns_work")
    assert "An AI Overview is not available for this search" in html
    assert classify_page(MANIFEST["how_does_dns_work"]["url"], html).aio_state is AioState.complete


def test_a_visible_failure_message_is_still_aio_incomplete():
    # Same real page, with Google's failure template actually shown.
    html, shown = re.subn(r'(<span jsname="L1sC6e" class="YWpX0d") style="display:none"', r"\1", html_of("how_does_dns_work"))
    assert shown == 2
    v = classify_page(MANIFEST["how_does_dns_work"]["url"], html)
    assert v.classification is Classification.aio_incomplete
    assert "can't generate" in v.reason


def test_hidden_marker_from_the_fetcher_counts_as_hidden():
    html = """<html><body><div id="search"><div id="rso"><a href="https://e.com"><h3>E</h3></a></div>
    <div><div role="heading" aria-level="2">AI Overview</div><div>""" + "DNS maps names to addresses. " * 10 + """</div>
    <span class="tpl">An AI Overview is not available for this search</span></div></div></body></html>"""
    assert classify_page("https://www.google.com/search?q=x", html).classification is Classification.aio_incomplete
    marked = html.replace('<span class="tpl">', '<span class="tpl" data-serp-hidden>')
    assert classify_page("https://www.google.com/search?q=x", marked).classification is Classification.ok


def test_an_answer_in_the_dom_counts_even_if_marked_hidden():
    # Google's AIO wraps its answer in display:contents elements, which a
    # visibility check can miss; the answer paragraphs are still in the DOM.
    html = """<html><body><div id="search"><div id="rso"><a href="https://e.com"><h3>E</h3></a></div>
    <div><div data-serp-hidden><div role="heading" aria-level="2">AI Overview</div></div>
    <div data-serp-hidden><div class="n6owBd">""" + "DNS maps names to addresses. " * 5 + """</div></div>
    <span data-serp-hidden>An AI Overview is not available for this search</span></div></div></body></html>"""
    v = classify_page("https://www.google.com/search?q=x", html)
    assert v.classification is Classification.ok and v.aio_state is AioState.complete


def test_an_ai_mode_placeholder_without_an_answer_is_not_served():
    html = """<html><body><div id="search"><div id="rso"><a href="https://e.com"><h3>E</h3></a></div>
    <div><div role="heading" aria-level="2">AI Overview</div><h3>AI Mode reply for t-mobile</h3>
    <span style="display:none">An AI Overview is not available for this search</span>""" + "<script>var x=1;</script>" * 20 + """</div></div></body></html>"""
    v = classify_page("https://www.google.com/search?q=t-mobile", html)
    assert v.classification is Classification.aio_incomplete and "not served" in v.reason


# --- classification + parsing + completeness, end to end -------------------------

@pytest.mark.parametrize("slug", sorted(DIRECT_PAGES))
async def test_direct_link_pages_are_valid_end_to_end(slug):
    out = await run(slug)
    assert out.ok, f"{slug}: {out.error_code} {out.error_message}"
    page = out.pages[0]
    assert page.organic and all(o.url and o.url.startswith("http") for o in page.organic)
    assert all(sl.url for o in page.organic for sl in o.sub_links)
    if slug in HAS_AIO:
        aio = page.ai_overview
        assert aio is not None and aio.intro and aio.sections and aio.sources
        assert all(src.url.startswith("http") and "/goto?" not in src.url for src in aio.sources)
    else:
        assert page.ai_overview is None


@pytest.mark.parametrize("slug", sorted(GOTO_PAGES))
async def test_goto_pages_fail_when_links_are_unresolved(slug):
    out = await run(slug, resolve_none)
    assert not out.ok and out.pages == []
    assert out.error_code == "parse_error" and out.status_code == 502
    assert "incomplete extraction" in out.error_message and "/goto" in out.error_message


@pytest.mark.parametrize("slug", sorted(GOTO_PAGES))
async def test_goto_pages_are_valid_once_links_are_resolved(slug):
    out = await run(slug, resolve_all)
    assert out.ok, f"{slug}: {out.error_code} {out.error_message}"
    page = out.pages[0]
    # Links on Google's own hosts (e.g. play.google.com) are never wrapped - direct hrefs.
    assert all(o.url.startswith(("https://resolved.test/", "https://play.google.com/")) for o in page.organic)
    assert page.organic[0].url.startswith("https://resolved.test/")
    assert all(sl.url.startswith("https://resolved.test/") for o in page.organic for sl in o.sub_links)
    if slug in HAS_AIO:
        assert page.ai_overview.sources
        assert all(src.url.startswith("https://resolved.test/") for src in page.ai_overview.sources)


@pytest.mark.parametrize("slug", sorted(GOTO_PAGES & HAS_AIO))
async def test_unresolved_aio_sources_alone_are_aio_incomplete(slug):
    tree = HTMLParser(html_of(slug))
    result_tokens = set(goto_tokens_needed(tree, parsers=[_organic, _paid]))

    def resolve_results_only(tokens):
        return {t: u for t, u in resolve_all(tokens).items() if t in result_tokens}

    out = await run(slug, resolve_results_only)
    assert not out.ok and out.error_code == "aio_incomplete"
    assert "source card" in out.error_message and out.first.aio_state is AioState.incomplete


def test_goto_tokens_needed_are_exactly_the_links_in_the_response():
    # Only links that end up in the response are resolved: here organic titles,
    # sitelinks and AI Overview source cards - not every /goto on the page.
    html = html_of("t_mobile")
    needed = goto_tokens_needed(HTMLParser(html))
    on_page = html.count('href="/goto?url=')
    assert 0 < len(needed) < on_page
    assert len(needed) == len(set(needed))
