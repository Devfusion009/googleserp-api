"""Fetcher.fetch: which failures are tried again, and what a retry costs."""
from app.classify import Classification
from app.config import Settings
from app.fetcher import Fetcher, FetchResult

UNREACHABLE = "browser/network error: net::ERR_TUNNEL_CONNECTION_FAILED"


def fetcher(outcomes, **settings):
    f = Fetcher(Settings(_env_file=None, proxy_unreachable_pause_ms=(10, 20), **settings), browsers=None)
    calls = []

    async def fetch_once(url, country, language):
        cls, reason = outcomes[len(calls)]
        calls.append(cls)
        res = FetchResult(url_sent=url, classification=cls, reason=reason)
        res.usage = {"document": 1}
        res.timings = {"bytes_in": 100}
        return res

    f._fetch_once = fetch_once
    return f, calls


async def test_an_unreachable_proxy_is_tried_once_more_and_both_attempts_are_counted():
    f, calls = fetcher([(Classification.network_error, UNREACHABLE), (Classification.ok, "results page")])
    res = await f.fetch("https://www.google.com/search?q=x", "US", "en")
    assert res.classification is Classification.ok and len(calls) == 2
    assert res.timings["attempt"] == 2 and res.usage["document"] == 2 and res.timings["bytes_in"] == 200


async def test_an_unreachable_proxy_is_retried_at_most_once():
    f, calls = fetcher([(Classification.network_error, UNREACHABLE)] * 3)
    res = await f.fetch("https://www.google.com/search?q=x", "US", "en")
    assert res.classification is Classification.network_error and len(calls) == 2


async def test_other_failures_are_not_retried():
    # a CAPTCHA, an incomplete overview, a timeout or another network error: Google may have
    # seen the request, so a retry on the same session is not free
    for outcome in [(Classification.blocked_captcha, "redirected to /sorry/"),
                    (Classification.aio_incomplete, "still loading"),
                    (Classification.timeout, "timed out: request deadline"),
                    (Classification.network_error, "browser/network error: net::ERR_CONNECTION_RESET")]:
        f, calls = fetcher([outcome, (Classification.ok, "results page")])
        res = await f.fetch("https://www.google.com/search?q=x", "US", "en")
        assert res.classification is outcome[0] and len(calls) == 1, outcome


async def test_no_retry_when_it_would_not_fit_the_deadline():
    f, calls = fetcher([(Classification.network_error, UNREACHABLE), (Classification.ok, "results page")],
                       request_deadline_ms=5)
    res = await f.fetch("https://www.google.com/search?q=x", "US", "en")
    assert res.classification is Classification.network_error and len(calls) == 1


async def test_the_retry_can_be_turned_off():
    f, calls = fetcher([(Classification.network_error, UNREACHABLE), (Classification.ok, "results page")],
                       proxy_unreachable_retries=0)
    res = await f.fetch("https://www.google.com/search?q=x", "US", "en")
    assert res.classification is Classification.network_error and len(calls) == 1
