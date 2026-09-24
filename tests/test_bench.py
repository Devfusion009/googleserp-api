"""Benchmark tests - offline. The API is driven in-process through httpx's ASGI
transport with the fetcher mocked, so no server, browser, or Google request."""
import asyncio

import httpx
import pytest

from app.classify import Classification
from app.config import Settings
from app.main import app, get_app_settings, get_fetcher
from bench import run_bench
from bench.run_bench import Call, call_api, nearest_rank, plan, render_report, summarize
from tests.test_api import FakeFetcher, failed_result, ok_result


def test_nearest_rank():
    assert nearest_rank([], 95) is None
    assert nearest_rank([100], 95) == 100
    vals = list(range(1, 21))  # 1..20
    assert nearest_rank(vals, 50) == 10
    assert nearest_rank(vals, 95) == 19
    assert nearest_rank(vals, 100) == 20
    assert nearest_rank([5, 1, 9], 50) == 5  # unsorted input


def test_plan_counts_and_limit():
    assert len(plan("mixed", 1, None)) == 15
    assert len(plan("difficult", 5, None)) == 5
    assert len(plan("both", 1, None)) == 16
    assert len(plan("mixed", 2, 3)) == 6
    # difficult URL kept byte-for-byte
    assert plan("difficult", 1, None)[0][1] == "https://www.google.com/search?q=flights%20to%20brussels%20from%20shanghai&gl=us&hl=us"


def test_refuses_over_cap_without_allow_more(monkeypatch, capsys):
    monkeypatch.setattr(run_bench, "get_settings", lambda: Settings(_env_file=None, max_live_requests_per_run=3))
    args = run_bench.parse_args(["--corpus", "mixed", "--min-delay", "0"])
    rc = asyncio.run(run_bench.run(args))
    assert rc == 2
    assert "Refusing" in capsys.readouterr().out


def _asgi_client(fetcher) -> httpx.AsyncClient:
    settings = Settings(_env_file=None)
    app.state.settings = settings
    app.dependency_overrides[get_fetcher] = lambda: fetcher
    app.dependency_overrides[get_app_settings] = lambda: settings
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_call_api_reads_classification_and_timings():
    url = "https://www.google.com/search?q=x&gl=us&hl=en"

    async def go():
        async with _asgi_client(FakeFetcher([ok_result(url)])) as client:
            return await call_api(client, "http://test", None, "mixed", url)

    call, data = asyncio.run(go())
    assert call.status == 200 and call.classification == "ok"
    assert call.timings["attempt"] == 1
    assert call.aio_state == "absent"
    assert call.aio_sources == 0
    assert data["results"][0]["organic"][0]["title"] == "Example Result"


def test_call_api_failure_carries_message_and_artifact():
    url = "https://www.google.com/search?q=x&gl=us&hl=en"
    r = failed_result(url, Classification.degraded_page, "results container missing")
    r.artifact_dir = "artifacts/x"

    async def go():
        async with _asgi_client(FakeFetcher([r])) as client:
            return await call_api(client, "http://test", None, "mixed", url)

    call, _ = asyncio.run(go())
    assert call.status == 502
    assert call.classification == "degraded_page"
    assert call.error_message == "results container missing"
    assert call.artifact_dir == "artifacts/x"


def test_summarize_counts_all_requests_in_latency_and_reports_pass_fail():
    calls = [
        Call("mixed", "u1", 200, "ok", 800, "complete", 5, {"nav_ms": 300, "total_ms": 800}),
        Call("mixed", "u2", 200, "ok", 1200, "absent", None, {"nav_ms": 400, "total_ms": 1200}),
        Call("mixed", "u3", 502, "aio_incomplete", 9000, "incomplete", None, {}, "AI Overview not finished", "artifacts/a"),
    ]
    s = summarize(calls)
    assert s["n"] == 3 and s["valid"] == 2
    assert not s["valid_pass"]
    assert s["p95"] == 9000  # the failure counts toward latency
    assert not s["p95_pass"]
    assert s["per_query"]["u1"]["complete"] == 1
    assert s["per_query"]["u3"]["appeared"] == 1 and s["per_query"]["u3"]["complete"] == 0
    assert s["stage_avgs"]["nav_ms"] == 350
    report = render_report("rid", run_bench.parse_args(["--min-delay", "0"]), {"mixed": s}, None)
    assert run_bench.LOCAL_LABEL in report
    assert "aio_incomplete" in report and "artifacts/a" in report
    assert "FAIL" in report
    assert "Caution" in report  # latency caveat when valid rate misses target


def test_run_stops_at_first_captcha(monkeypatch, tmp_path):
    monkeypatch.setattr(run_bench, "REPORTS", tmp_path)
    seen = []

    async def fake_call_api(client, base_url, api_key, corpus, url):
        seen.append(url)
        cls = "blocked_captcha" if len(seen) == 2 else "ok"
        return Call(corpus, url, 429 if cls != "ok" else 200, cls, 100, "absent", None, {}), {}

    monkeypatch.setattr(run_bench, "call_api", fake_call_api)
    args = run_bench.parse_args(["--corpus", "mixed", "--min-delay", "0"])
    rc = asyncio.run(run_bench.run(args))
    assert rc == 0
    assert len(seen) == 2  # nothing sent after the CAPTCHA
    reports = list(tmp_path.glob("*/report.md"))
    assert reports and "Run stopped early" in reports[0].read_text()
