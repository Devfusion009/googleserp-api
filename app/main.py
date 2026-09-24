"""FastAPI app: POST /serp, GET /health.

Wiring only - all the real work (fetching, classifying, parsing) lives in
fetcher.py / classify.py / parsers/. This module's job is: validate the
request, drive one Fetcher per page, turn each fetched page into the client's
exact JSON shape, and report an honest error the moment any page fails.
"""
import json
import logging
import math
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from selectolax.parser import HTMLParser

from .browser import BrowserManager
from .classify import STATUS_FOR, Classification
from .classify import find_aio_root
from .config import Settings, get_settings
from .fetcher import Fetcher
from .models import (
    AioSection,
    AioSource,
    AiOverview,
    KnowledgePanel,
    OrganicItem,
    PageResult,
    SerpRequest,
    SerpResponse,
    SubLink,
)
from .parsers.ads import parse_ads
from .parsers.aio import parse_aio
from .parsers.knowledge_panel import parse_knowledge_panel
from .parsers.misc import parse_corrections, parse_number_of_results, parse_suggestions
from .parsers.organic import parse_organic_results
from .urls import InvalidUrl, page_url, validate_search_url

log = logging.getLogger("serp.api")


def _configure_logging() -> None:
    """uvicorn only configures its own loggers; without this, every serp.*
    line (URL sent, final URL, proxy used, classification, timings) is dropped."""
    serp = logging.getLogger("serp")
    if not serp.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        serp.addHandler(handler)
        serp.setLevel(logging.INFO)
        serp.propagate = False


_configure_logging()

RESULTS_PER_PAGE = 10

# error code -> (classification match, http status) used to build the response
ERROR_CODE_FOR = {
    Classification.blocked_captcha: "blocked_captcha",
    Classification.consent_wall: "consent_wall",
    Classification.degraded_page: "degraded_page",
    Classification.aio_incomplete: "aio_incomplete",
    Classification.parse_error: "parse_error",
    Classification.timeout: "timeout",
    Classification.network_error: "network_error",
    Classification.invalid_url: "invalid_url",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    browsers = BrowserManager(settings)
    await browsers.start()
    app.state.browsers = browsers
    app.state.fetcher = Fetcher(settings, browsers)
    try:
        yield
    finally:
        await browsers.stop()


app = FastAPI(title="Google SERP API", lifespan=lifespan)


def get_fetcher(request: Request) -> Fetcher:
    """A dependency, not a direct app.state read, so tests can override it
    with `app.dependency_overrides[get_fetcher] = lambda: fake_fetcher`."""
    return request.app.state.fetcher


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_app_settings),
) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")


@app.exception_handler(RequestValidationError)
async def on_bad_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    """A malformed body (bad JSON, wrong types, missing `url`) is still a 400
    with the client's own error envelope, not FastAPI's default 422 shape."""
    body = SerpResponse(status_code=400, requests_used=0, elapsed_time=0, results=[], error="invalid_url", error_message=str(exc))
    resp = JSONResponse(status_code=400, content=body.model_dump())
    resp.headers["X-Request-Id"] = str(uuid.uuid4())
    resp.headers["X-Classification"] = "invalid_url"
    return resp


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def _build_page_result(page_num: int, tree: HTMLParser, warnings: list[str]) -> PageResult:
    organic_raw, w = parse_organic_results(tree.css_first("#rso") or tree)
    warnings.extend(w)
    organic = [
        OrganicItem(url=o.url, title=o.title, content=o.content, sub_links=[SubLink(title=s.title, url=s.url) for s in o.sub_links])
        for o in organic_raw
    ]

    ad_warnings: list[str] = []
    paid_raw = parse_ads(tree.css_first("#tads"), ad_warnings) + parse_ads(tree.css_first("#bottomads"), ad_warnings)
    warnings.extend(ad_warnings)
    paid = [
        OrganicItem(url=a.url, title=a.title, content=a.content, sub_links=[SubLink(title=s.title, url=s.url) for s in a.sub_links])
        for a in paid_raw
    ]

    ai_overview = None
    aio_root = find_aio_root(tree)
    if aio_root is not None:
        parsed = parse_aio(aio_root)
        warnings.extend(parsed.warnings)
        if parsed.intro or parsed.sections or parsed.sources:
            ai_overview = AiOverview(
                intro=parsed.intro,
                sections=[AioSection(title=s.title, text=s.text) for s in parsed.sections],
                sources=[AioSource(title=s.title, url=s.url, snippet=s.snippet) for s in parsed.sources],
            )

    kp = parse_knowledge_panel(tree)
    knowledge_panel = (
        KnowledgePanel(title=kp.title, subtitle=kp.subtitle, description=kp.description, source_url=kp.source_url, facts=kp.facts)
        if kp is not None
        else None
    )

    return PageResult(
        page=page_num,
        paid=paid,
        organic=organic,
        ai_overview=ai_overview,
        knowledge_panel=knowledge_panel,
        number_of_results=parse_number_of_results(tree),
        suggestions=parse_suggestions(tree),
        corrections=parse_corrections(tree),
    )


def _set_debug_headers(resp, request_id: str, classification: str, result=None) -> None:
    resp.headers["X-Request-Id"] = request_id
    resp.headers["X-Classification"] = classification
    if result is not None:
        resp.headers["X-AIO-State"] = result.aio_state.value
        resp.headers["X-Timings"] = json.dumps(result.timings)
        if result.artifact_dir:
            resp.headers["X-Artifact-Dir"] = result.artifact_dir


def _error_response(
    request_id: str, code: str, message: str, status_code: int, elapsed_ms: int, requests_used: int, result=None
) -> JSONResponse:
    body = SerpResponse(
        status_code=status_code,
        requests_used=requests_used,
        elapsed_time=elapsed_ms,
        results=[],
        error=code,
        error_message=message,
    )
    resp = JSONResponse(status_code=status_code, content=body.model_dump())
    _set_debug_headers(resp, request_id, code, result)
    return resp


@app.post("/serp", dependencies=[Depends(require_api_key)])
async def serp(
    req: SerpRequest,
    fetcher: Fetcher = Depends(get_fetcher),
):
    request_id = str(uuid.uuid4())
    t0 = time.perf_counter()

    def elapsed() -> int:
        return int((time.perf_counter() - t0) * 1000)

    try:
        validate_search_url(req.url)
    except InvalidUrl as e:
        return _error_response(request_id, "invalid_url", str(e), 400, elapsed(), 0)

    num_pages = max(1, math.ceil(req.results / RESULTS_PER_PAGE))
    requests_used = 0
    pages: list[PageResult] = []
    first = None
    all_warnings: list[str] = []

    for page_idx in range(num_pages):
        url = page_url(req.url, page_idx)
        result = await fetcher.fetch(url, req.country, req.language)
        requests_used += result.timings.get("attempt", 1)
        if page_idx == 0:
            first = result

        if result.classification is not Classification.ok:
            code = ERROR_CODE_FOR.get(result.classification, "network_error")
            status_code = STATUS_FOR.get(result.classification, 502)
            log.warning("request_id=%s page=%d classification=%s reason=%s", request_id, page_idx + 1, code, result.reason)
            return _error_response(request_id, code, result.reason, status_code, elapsed(), requests_used, result)

        try:
            tree = HTMLParser(result.html or "")
            page_result = _build_page_result(page_idx + 1, tree, all_warnings)
        except Exception:
            log.exception("request_id=%s page=%d parse_error", request_id, page_idx + 1)
            return _error_response(request_id, "parse_error", "failed to parse the page", 502, elapsed(), requests_used, result)
        if not page_result.organic:
            # The brief counts a results page with no organic results as degraded,
            # even when the results container itself was present.
            log.warning("request_id=%s page=%d degraded_page: zero organic results", request_id, page_idx + 1)
            return _error_response(
                request_id, "degraded_page", "page loaded but had zero organic results", 502, elapsed(), requests_used, result
            )
        pages.append(page_result)

    for w in all_warnings:
        log.warning("request_id=%s parse warning: %s", request_id, w)

    if not req.return_json:
        resp = HTMLResponse(content=first.html or "")
    else:
        body = SerpResponse(status_code=200, requests_used=requests_used, elapsed_time=elapsed(), results=pages)
        resp = JSONResponse(content=body.model_dump())
    _set_debug_headers(resp, request_id, "ok", first)
    return resp
