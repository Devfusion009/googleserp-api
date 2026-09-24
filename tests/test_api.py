"""API-layer tests, fetcher mocked - no browser, no live requests."""
import json

import pytest
from fastapi.testclient import TestClient

from app.classify import AioState, Classification
from app.config import Settings
from app.fetcher import FetchResult
from app.main import app, get_app_settings, get_fetcher

DIFFICULT_URL = "https://www.google.com/search?q=flights%20to%20brussels%20from%20shanghai&gl=us&hl=us"

SIMPLE_PAGE_HTML = """
<html><body>
<div id="search"><div id="rso">
<div data-hveid="x1"><a href="https://example.com/a"><h3>Example Result</h3></a><div>Example snippet text.</div></div>
</div></div>
<div id="tads"></div>
<div id="result-stats">About 1,230,000 results (0.40 seconds)</div>
</body></html>
"""


class FakeFetcher:
    """Returns one FetchResult per call, in order; records every call made."""

    def __init__(self, results: list[FetchResult]):
        self._results = list(results)
        self.calls: list[tuple[str, str | None, str | None]] = []

    async def fetch(self, url: str, country: str | None, language: str | None) -> FetchResult:
        self.calls.append((url, country, language))
        return self._results.pop(0) if self._results else self._results[-1]


def ok_result(url: str, html: str = SIMPLE_PAGE_HTML, attempt: int = 1) -> FetchResult:
    r = FetchResult(url_sent=url, final_url=url, html=html, classification=Classification.ok, aio_state=AioState.absent)
    r.timings = {"attempt": attempt, "total_ms": 500}
    return r


def failed_result(url: str, classification: Classification, reason: str, attempt: int = 1) -> FetchResult:
    r = FetchResult(url_sent=url, final_url=url, html="<html></html>", classification=classification, reason=reason)
    r.timings = {"attempt": attempt, "total_ms": 500}
    return r


@pytest.fixture
def client_for():
    """client_for(fetcher, settings=None) -> TestClient with dependencies overridden.
    Never triggers the real lifespan, so no browser is ever launched."""

    def _make(fetcher, settings: Settings | None = None) -> TestClient:
        settings = settings or Settings(_env_file=None)
        app.state.settings = settings
        app.dependency_overrides[get_fetcher] = lambda: fetcher
        app.dependency_overrides[get_app_settings] = lambda: settings
        return TestClient(app)

    yield _make
    app.dependency_overrides.clear()


def test_health_needs_no_api_key(client_for):
    client = client_for(FakeFetcher([]), Settings(_env_file=None, api_key="secret"))
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_serp_success_minimal(client_for):
    fetcher = FakeFetcher([ok_result("https://www.google.com/search?q=x&gl=us&hl=en")])
    client = client_for(fetcher)
    resp = client.post("/serp", json={"url": "https://www.google.com/search?q=x&gl=us&hl=en", "results": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status_code"] == 200
    assert body["error"] is None
    assert body["requests_used"] == 1
    assert len(body["results"]) == 1
    page = body["results"][0]
    assert page["page"] == 1
    assert page["organic"] == [{"url": "https://example.com/a", "title": "Example Result", "content": "Example snippet text.", "sub_links": []}]
    assert page["number_of_results"] == 1230000
    assert page["ai_overview"] is None
    assert page["knowledge_panel"] is None
    assert "X-Request-Id" in resp.headers
    assert resp.headers["X-Classification"] == "ok"


def test_serp_difficult_url_reaches_fetcher_unchanged(client_for):
    fetcher = FakeFetcher([ok_result(DIFFICULT_URL)])
    client = client_for(fetcher)
    resp = client.post("/serp", json={"url": DIFFICULT_URL, "results": 10, "country": "US", "language": "en"})
    assert resp.status_code == 200
    assert len(fetcher.calls) == 1
    called_url, country, language = fetcher.calls[0]
    assert called_url == DIFFICULT_URL
    assert called_url.encode() == DIFFICULT_URL.encode()
    assert "hl=us" in called_url
    assert (country, language) == ("US", "en")


def test_serp_multi_page_requests_more_than_10(client_for):
    url = "https://www.google.com/search?q=x&gl=us&hl=en"
    fetcher = FakeFetcher([ok_result(url), ok_result(url + "&start=10")])
    client = client_for(fetcher)
    resp = client.post("/serp", json={"url": url, "results": 15})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 2
    assert body["results"][0]["page"] == 1
    assert body["results"][1]["page"] == 2
    assert body["requests_used"] == 2
    assert fetcher.calls[0][0] == url  # page 1 untouched
    assert fetcher.calls[1][0] == url + "&start=10"


def test_serp_invalid_url_rejected_before_any_fetch(client_for):
    fetcher = FakeFetcher([])
    client = client_for(fetcher)
    resp = client.post("/serp", json={"url": "https://www.bing.com/search?q=x", "results": 10})
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "invalid_url"
    assert body["results"] == []
    assert fetcher.calls == []


def test_serp_malformed_body_is_400_not_422(client_for):
    client = client_for(FakeFetcher([]))
    resp = client.post("/serp", json={"results": 10})  # missing required `url`
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_url"


@pytest.mark.parametrize(
    "classification,expected_status,expected_code",
    [
        (Classification.blocked_captcha, 429, "blocked_captcha"),
        (Classification.consent_wall, 502, "consent_wall"),
        (Classification.degraded_page, 502, "degraded_page"),
        (Classification.aio_incomplete, 502, "aio_incomplete"),
        (Classification.timeout, 504, "timeout"),
        (Classification.network_error, 502, "network_error"),
    ],
)
def test_serp_failure_classifications_map_to_status_and_empty_results(client_for, classification, expected_status, expected_code):
    url = "https://www.google.com/search?q=x&gl=us&hl=en"
    fetcher = FakeFetcher([failed_result(url, classification, "some reason")])
    client = client_for(fetcher)
    resp = client.post("/serp", json={"url": url, "results": 10})
    assert resp.status_code == expected_status
    body = resp.json()
    assert body["status_code"] == expected_status
    assert body["error"] == expected_code
    assert body["error_message"] == "some reason"
    assert body["results"] == []


def test_serp_second_page_failure_discards_first_page(client_for):
    url = "https://www.google.com/search?q=x&gl=us&hl=en"
    fetcher = FakeFetcher([ok_result(url), failed_result(url + "&start=10", Classification.blocked_captcha, "captcha")])
    client = client_for(fetcher)
    resp = client.post("/serp", json={"url": url, "results": 15})
    assert resp.status_code == 429
    body = resp.json()
    assert body["error"] == "blocked_captcha"
    assert body["results"] == []


def test_serp_return_json_false_returns_raw_html(client_for):
    url = "https://www.google.com/search?q=x&gl=us&hl=en"
    fetcher = FakeFetcher([ok_result(url)])
    client = client_for(fetcher)
    resp = client.post("/serp", json={"url": url, "results": 10, "return_json": False})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "Example Result" in resp.text


def test_api_key_enforced_when_configured(client_for):
    url = "https://www.google.com/search?q=x&gl=us&hl=en"
    fetcher = FakeFetcher([ok_result(url)])
    client = client_for(fetcher, Settings(_env_file=None, api_key="secret123"))

    resp = client.post("/serp", json={"url": url, "results": 10})
    assert resp.status_code == 401

    resp = client.post("/serp", json={"url": url, "results": 10}, headers={"X-API-Key": "secret123"})
    assert resp.status_code == 200


def test_api_key_not_required_when_unset(client_for):
    url = "https://www.google.com/search?q=x&gl=us&hl=en"
    fetcher = FakeFetcher([ok_result(url)])
    client = client_for(fetcher, Settings(_env_file=None, api_key=""))
    resp = client.post("/serp", json={"url": url, "results": 10})
    assert resp.status_code == 200


def test_serp_response_headers_carry_debug_info(client_for):
    url = "https://www.google.com/search?q=x&gl=us&hl=en"
    fetcher = FakeFetcher([ok_result(url)])
    client = client_for(fetcher)
    resp = client.post("/serp", json={"url": url, "results": 10})
    assert resp.headers["X-AIO-State"] == "absent"
    timings = json.loads(resp.headers["X-Timings"])
    assert timings["attempt"] == 1
