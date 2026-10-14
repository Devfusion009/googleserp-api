from pathlib import Path

from selectolax.parser import HTMLParser

from app.classify import AioState, Classification, aio_loading, classify_page

F = Path(__file__).parent / "fixtures" / "classifier"
SERP = "https://www.google.com/search?q=x&gl=us&hl=en"


def read(name):
    return (F / name).read_text(encoding="utf-8")


def test_real_captcha_by_url_and_text():
    html = read("real_captcha_sorry.html")
    assert classify_page("https://www.google.com/sorry/index?continue=x", html).classification is Classification.blocked_captcha
    # even if the URL looked normal, the page text alone is enough
    assert classify_page(SERP, html).classification is Classification.blocked_captcha


def test_consent_wall():
    assert classify_page("https://consent.google.com/ml?continue=x", "<html></html>").classification is Classification.consent_wall
    assert classify_page(SERP, read("synthetic_consent.html")).classification is Classification.consent_wall


def test_js_required_is_degraded():
    assert classify_page(SERP, read("synthetic_js_required.html")).classification is Classification.degraded_page


def test_missing_container_is_degraded():
    assert classify_page(SERP, read("synthetic_no_results_container.html")).classification is Classification.degraded_page


def test_zero_organic_is_degraded():
    html = '<html><body><div id="search"><div id="rso"></div></div></body></html>'
    assert classify_page(SERP, html, organic_count=0).classification is Classification.degraded_page


def test_aio_loading_is_incomplete():
    v = classify_page(SERP, read("synthetic_aio_loading.html"), organic_count=1)
    assert v.classification is Classification.aio_incomplete
    assert v.aio_state is AioState.incomplete


def test_aio_loading_says_why_a_placeholder_is_still_loading():
    # live q18 (Poland, 2026-10-10): captured on the 'AI Mode reply' placeholder while the
    # answer was still streaming in (the screenshot taken just after shows it)
    why = aio_loading(HTMLParser(read("real_aio_placeholder_streaming.html")))
    assert why is not None and "placeholder" in why


def test_aio_loading_is_none_when_complete_absent_or_failed():
    complete = '<div><h2>AI Overview</h2><div class="n6owBd">' + "An answer. " * 30 + "</div></div>"
    failed = '<div><h2>AI Overview</h2><span>An AI Overview is not available for this search</span>' + "<p>x</p>" * 3 + "</div>"
    for html in (complete, "<div>no overview</div>", failed):
        assert aio_loading(HTMLParser(f"<html><body>{html}</body></html>")) is None


def test_plain_results_ok_without_aio():
    html = '<html><body><div id="search"><div id="rso"><div><a href="https://e.com"><h3>E</h3></a></div></div></div></body></html>'
    v = classify_page(SERP, html, organic_count=1)
    assert v.classification is Classification.ok and v.aio_state is AioState.absent
