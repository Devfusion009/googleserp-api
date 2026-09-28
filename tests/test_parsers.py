"""Parser tests against the real captured fixtures (never hand-written HTML)."""
import json
from pathlib import Path

import pytest
from selectolax.parser import HTMLParser

from app.classify import find_aio_root
from app.links import LinkMap, goto_token
from app.parsers.ads import parse_ads
from app.parsers.context import ParseContext
from app.parsers.knowledge_panel import parse_knowledge_panel
from app.parsers.misc import parse_number_of_results, parse_suggestions
from app.parsers.organic import parse_organic_results
from app.parsers.aio import parse_aio

FIXTURES = Path(__file__).parent / "fixtures"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text())

HAS_AIO = {
    "t_mobile", "mobile", "apple", "best_cell_phone_plans", "car_insurance_quotes",
    "crm_software", "how_does_dns_work", "why_is_the_sky_blue",
    "best_supplements_for_sleep",
    "how_to_replace_a_kitchen_faucet_cartridge_delta_1400_series",
    "difficult_flights_to_brussels_from_shanghai",
}
NO_AIO = {"wikipedia", "chase_bank_login", "coffee_shops_near_seattle", "plumber_austin_tx", "eiffel_tower"}

# Known first-organic-result {title substring: url} per fixture, to catch a
# parser regression without hand-writing full expected pages.
FIRST_ORGANIC = {
    "how_does_dns_work": ("What is DNS", "https://www.cloudflare.com/learning/dns/what-is-dns/"),
    "wikipedia": ("Wikipedia", "https://www.wikipedia.org"),
    "eiffel_tower": ("Origins", None),  # first #rso item varies by ad presence; just check it parses
}


def tree_for(slug: str) -> HTMLParser:
    html = (FIXTURES / f"{slug}.html").read_text(encoding="utf-8")
    return HTMLParser(html)


@pytest.mark.parametrize("slug", sorted(MANIFEST.keys()))
def test_every_fixture_has_nonempty_organic(slug):
    tree = tree_for(slug)
    rso = tree.css_first("#rso")
    assert rso is not None, f"{slug}: #rso missing"
    results, warnings = parse_organic_results(rso)
    assert len(results) > 0, f"{slug}: organic came back empty"
    for r in results:
        assert r.title, f"{slug}: an organic result has no title"


def test_dns_first_result_title_and_url():
    tree = tree_for("how_does_dns_work")
    results, _ = parse_organic_results(tree.css_first("#rso"))
    assert results[0].title == "What is DNS? | Learning Center"
    assert results[0].url == "https://www.cloudflare.com/learning/dns/what-is-dns/"
    assert results[0].content and "phonebook" in results[0].content.lower()
    assert any(sl.url and sl.url.startswith("https://www.cloudflare.com") for sl in results[0].sub_links)


def test_goto_result_url_is_never_rebuilt_from_the_breadcrumb():
    # wikipedia's links are all /goto-wrapped. Unresolved, the url is None and
    # the gap is recorded - the breadcrumb ("https://www.wikipedia.org") is not
    # used, it is often only the domain.
    tree = tree_for("wikipedia")
    ctx = ParseContext()
    results, _ = parse_organic_results(tree.css_first("#rso"), ctx)
    assert results[0].title == "Wikipedia"
    assert results[0].url is None
    assert any("Wikipedia" in g.reason and "/goto" in g.reason for g in ctx.gaps)


def test_goto_result_url_comes_from_the_resolved_map():
    tree = tree_for("wikipedia")
    href = tree.css_first("#rso a h3").parent.attributes["href"]
    token = goto_token(href)
    ctx = ParseContext(links=LinkMap(resolved={token: "https://www.wikipedia.org/"}))
    results, _ = parse_organic_results(tree.css_first("#rso"), ctx)
    assert results[0].url == "https://www.wikipedia.org/"


def test_goto_sitelinks_resolve_through_the_map_and_are_gaps_otherwise():
    tree = tree_for("wikipedia")
    ctx = ParseContext()
    results, _ = parse_organic_results(tree.css_first("#rso"), ctx)
    langs = results[0].sub_links
    assert [sl.title for sl in langs][:2] == ["English", "Deutsch"]
    assert all(sl.url is None for sl in langs)  # never a fabricated url...
    assert sum("sub-link" in g.reason for g in ctx.gaps) == len(langs)  # ...and each one is a gap

    resolved = {t: f"https://resolved.test/{i}" for i, t in enumerate(ctx.links.wanted)}
    ctx2 = ParseContext(links=LinkMap(resolved=resolved))
    results2, _ = parse_organic_results(tree_for("wikipedia").css_first("#rso"), ctx2)
    assert all(sl.url and sl.url.startswith("https://resolved.test/") for sl in results2[0].sub_links)
    assert not ctx2.gaps


def test_more_results_from_site_link_is_its_real_google_url():
    tree = tree_for("why_is_the_sky_blue")
    results, _ = parse_organic_results(tree.css_first("#rso"), ParseContext())
    more = [sl for r in results for sl in r.sub_links if sl.title.startswith("More results from")]
    assert more and more[0].url.startswith("https://www.google.com/search?q=why+is+the+sky+blue+site:www.reddit.com")


def test_distinct_unresolved_results_with_same_title_are_not_merged():
    # apple has two different "Apple" social-profile results; before, an
    # unresolved url made them share the dedupe key and one was dropped.
    tree = tree_for("apple")
    results, _ = parse_organic_results(tree.css_first("#rso"), ParseContext())
    assert [r.title for r in results].count("Apple") == 3


# On these fixtures Google wrapped every AIO source link in /goto. Offline the
# destinations are unknown: sources stay empty and every card is a gap (the page
# fails as aio_incomplete); live, the fetcher resolves them - see test_pipeline.py.
GOTO_WRAPPED_AIO_SOURCES = {"apple", "best_cell_phone_plans", "mobile", "t_mobile"}


@pytest.mark.parametrize("slug", sorted(HAS_AIO))
def test_aio_present_fixtures_have_intro_and_sections(slug):
    tree = tree_for(slug)
    root = find_aio_root(tree)
    assert root is not None, f"{slug}: expected an AI Overview, classify.find_aio_root found none"
    result = parse_aio(root)
    assert result.intro, f"{slug}: AI Overview intro is empty"
    assert result.sections, f"{slug}: AI Overview has no sections"
    for s in result.sections:
        assert s.text, f"{slug}: section {s.title!r} has empty text"
    if slug in GOTO_WRAPPED_AIO_SOURCES:
        ctx = ParseContext()
        assert parse_aio(find_aio_root(tree_for(slug)), ctx).sources == []
        assert ctx.gaps and all(g.field == "ai_overview" for g in ctx.gaps)
        return
    assert result.sources, f"{slug}: AI Overview has no sources"
    for src in result.sources:
        assert src.url.startswith("http"), f"{slug}: a source url is not absolute: {src.url!r}"
        assert "/url?" not in src.url and "/goto?" not in src.url, f"{slug}: a redirect wrapper was not resolved: {src.url!r}"


def test_google_hosted_citation_is_kept():
    # The flights AI Overview cites Google Flights; it is a genuine source.
    tree = tree_for("difficult_flights_to_brussels_from_shanghai")
    ctx = ParseContext()
    sources = parse_aio(find_aio_root(tree), ctx).sources
    assert any(s.url.startswith("https://www.google.com/travel/flights") for s in sources)
    assert len(sources) == 5 and not ctx.gaps


def test_product_cards_are_the_only_cards_left_out():
    # apple and best_cell_phone_plans have shopping cards (no href, role=button,
    # data-cid). They are skipped; every other card is either a source or a gap.
    for slug, products in (("apple", 1), ("best_cell_phone_plans", 2)):
        root = find_aio_root(tree_for(slug))
        cards = root.css("li.h7wxwc")
        ctx = ParseContext()
        parse_aio(root, ctx)
        skipped = [w for w in ctx.warnings if "shopping element" in w]
        source_gaps = [g for g in ctx.gaps if g.reason.startswith("source card")]
        assert len(skipped) == products
        assert len(source_gaps) == len(cards) - products  # offline: every other card is an unresolved /goto


def test_a_linkless_card_that_is_not_a_product_is_a_gap():
    tree = tree_for("apple")
    root = find_aio_root(tree)
    card_link = next(a for a in root.css("li.h7wxwc a.vIWmYe") if a.attributes.get("data-cid"))
    del card_link.attrs["data-cid"]  # no longer recognisably a shopping card
    ctx = ParseContext()
    parse_aio(root, ctx)
    assert not any("shopping element" in w for w in ctx.warnings)
    assert any("no usable link" in g.reason for g in ctx.gaps)


@pytest.mark.parametrize("slug", sorted(NO_AIO))
def test_no_aio_fixtures_have_no_ai_overview(slug):
    tree = tree_for(slug)
    root = find_aio_root(tree)
    assert root is None, f"{slug}: expected no AI Overview, but find_aio_root found one"


def test_car_insurance_ads_and_aio_together():
    tree = tree_for("car_insurance_quotes")
    ctx = ParseContext()
    ads = parse_ads(tree.css_first("#tads"), ctx) + parse_ads(tree.css_first("#bottomads"), ctx)
    assert not ctx.gaps
    assert len(ads) >= 1
    assert all(a.url and a.url.startswith("http") for a in ads)
    assert all(a.title for a in ads)

    root = find_aio_root(tree)
    assert root is not None
    result = parse_aio(root)
    assert len(result.sources) >= 5  # the fully-expanded "Show all" list


def test_ads_empty_is_normal_not_a_failure():
    tree = tree_for("wikipedia")
    ctx = ParseContext()
    assert parse_ads(tree.css_first("#tads"), ctx) == []
    assert ctx.warnings == [] and ctx.gaps == []


def test_knowledge_panel_eiffel_tower():
    tree = tree_for("eiffel_tower")
    kp = parse_knowledge_panel(tree)
    assert kp is not None
    assert kp.title == "Eiffel Tower"
    assert kp.subtitle == "Historical landmark"
    assert kp.description and "lattice tower" in kp.description
    assert kp.source_url and kp.source_url.startswith("https://")
    assert kp.facts.get("Height")
    assert "Address" in kp.facts


@pytest.mark.parametrize("slug", ["apple", "t_mobile", "how_does_dns_work"])
def test_knowledge_panel_null_when_rhs_is_empty_placeholder(slug):
    tree = tree_for(slug)
    assert parse_knowledge_panel(tree) is None


def test_number_of_results_parses_and_is_none_safe():
    tree = tree_for("how_does_dns_work")
    n = parse_number_of_results(tree)
    assert isinstance(n, int) and n > 0


def test_suggestions_from_bottom_of_page_not_knowledge_panel_carousel():
    tree = tree_for("t_mobile")
    suggestions = parse_suggestions(tree)
    assert suggestions, "t_mobile should have a 'People also search for' block at the bottom"
    assert all("T-Mobile" in s or "t-mobile" in s.lower() for s in suggestions)
    assert "Deutsche Telekom" not in suggestions  # that's the knowledge panel's related-entity carousel, not a search suggestion
