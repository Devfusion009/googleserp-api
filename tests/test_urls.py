import pytest

from app.urls import InvalidUrl, page_url, strip_text_fragment, unwrap_google_redirect, validate_search_url

DIFFICULT = "https://www.google.com/search?q=flights%20to%20brussels%20from%20shanghai&gl=us&hl=us"


@pytest.mark.parametrize("url", [
    DIFFICULT,
    "https://www.google.com/search?q=how%20does%20dns%20work&gl=us&hl=en",
    "https://google.com/search?q=apple",
])
def test_valid_urls_returned_unchanged(url):
    assert validate_search_url(url) is url


@pytest.mark.parametrize("url", [
    "", "https://www.bing.com/search?q=x", "https://www.google.com/maps?q=x",
    "https://www.google.co.uk/search?q=x", "https://evil.com/?u=https://www.google.com/search?q=x",
    "https://www.google.com.evil.com/search?q=x", "ftp://www.google.com/search?q=x",
    "https://user:pw@www.google.com/search?q=x", "https://www.google.com:8080/search?q=x",
    "https://www.google.com/search?hl=en", "https://www.google.com/search/?q=x",
    " https://www.google.com/search?q=x",
])
def test_invalid_urls_rejected(url):
    with pytest.raises(InvalidUrl):
        validate_search_url(url)


def test_page_url_page1_untouched_and_start_appended():
    assert page_url(DIFFICULT, 0) is DIFFICULT
    assert page_url(DIFFICULT, 1) == DIFFICULT + "&start=10"
    assert page_url(DIFFICULT, 2) == DIFFICULT + "&start=20"


def test_unwrap_redirect():
    assert unwrap_google_redirect("/url?q=https://example.com/a%3Fb%3D1&sa=U&ved=x") == "https://example.com/a?b=1"
    assert unwrap_google_redirect("https://www.google.com/url?url=https://x.org/&sa=t") == "https://x.org/"
    assert unwrap_google_redirect("https://example.com/p") == "https://example.com/p"
    assert unwrap_google_redirect(None) is None


def test_strip_text_fragment():
    assert strip_text_fragment("https://a.com/p#:~:text=hello%20world") == "https://a.com/p"
    assert strip_text_fragment("https://a.com/p#sec:~:text=x") == "https://a.com/p#sec"
    assert strip_text_fragment("https://a.com/p#sec") == "https://a.com/p#sec"
    assert strip_text_fragment("https://a.com/p") == "https://a.com/p"
