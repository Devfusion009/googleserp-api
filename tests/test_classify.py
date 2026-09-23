from pathlib import Path

from app.classify import AioState, Classification, classify_page

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


def test_plain_results_ok_without_aio():
    html = '<html><body><div id="search"><div id="rso"><div><a href="https://e.com"><h3>E</h3></a></div></div></div></body></html>'
    v = classify_page(SERP, html, organic_count=1)
    assert v.classification is Classification.ok and v.aio_state is AioState.absent
