"""Parser tests against the real captured fixtures (never hand-written HTML)."""
import json
from pathlib import Path

import pytest
from selectolax.parser import HTMLParser

from app.classify import find_aio_root
from app.parsers.ads import parse_ads
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


def test_wikipedia_first_result_title_and_url():
    tree = tree_for("wikipedia")
    results, _ = parse_organic_results(tree.css_first("#rso"))
    assert results[0].title == "Wikipedia"
    assert results[0].url == "https://www.wikipedia.org"


def test_wikipedia_sitelinks_without_real_hrefs_are_null_not_guessed():
    tree = tree_for("wikipedia")
    results, _ = parse_organic_results(tree.css_first("#rso"))
    wikipedia_org = results[0]
    assert wikipedia_org.sub_links  # the language-switcher row is picked up...
    assert all(sl.url is None for sl in wikipedia_org.sub_links)  # ...but never with a fabricated url


# On these fixtures Google wrapped every AIO source link (and gave no cite/
# breadcrumb fallback) in its opaque /goto redirect - seen the same way on
# organic results in app/parsers/organic.py. We can't decode it (that would be
# reverse-engineering Google's script) and there's no visible fallback text
# here to rebuild a URL from, so every source in the panel is correctly
# skipped rather than emitted with a guessed or missing url. A real gap to
# flag for the client - see PROGRESS.md.
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
        assert result.sources == []
        return
    assert result.sources, f"{slug}: AI Overview has no sources"
    for src in result.sources:
        assert src.url.startswith("http"), f"{slug}: a source url is not absolute: {src.url!r}"
        assert "google.com" not in src.url, f"{slug}: a source url points at google.com"


@pytest.mark.parametrize("slug", sorted(NO_AIO))
def test_no_aio_fixtures_have_no_ai_overview(slug):
    tree = tree_for(slug)
    root = find_aio_root(tree)
    assert root is None, f"{slug}: expected no AI Overview, but find_aio_root found one"


def test_car_insurance_ads_and_aio_together():
    tree = tree_for("car_insurance_quotes")
    warnings = []
    ads = parse_ads(tree.css_first("#tads"), warnings) + parse_ads(tree.css_first("#bottomads"), warnings)
    assert len(ads) >= 1
    assert all(a.url and a.url.startswith("http") for a in ads)
    assert all(a.title for a in ads)

    root = find_aio_root(tree)
    assert root is not None
    result = parse_aio(root)
    assert len(result.sources) >= 5  # the fully-expanded "Show all" list


def test_ads_empty_is_normal_not_a_failure():
    tree = tree_for("wikipedia")
    warnings = []
    assert parse_ads(tree.css_first("#tads"), warnings) == []
    assert warnings == []


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
