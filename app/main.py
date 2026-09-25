"""FastAPI app: POST /serp, GET /health.

Wiring only - all the real work (fetching, classifying, parsing) lives in
fetcher.py / classify.py / parsers/. This module's job is: validate the
request, drive one Fetcher per page, turn each fetched page into the client's
exact JSON shape, and report an honest error the moment any page fails.
"""
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse

from .browser import BrowserManager
from .config import Settings, get_settings
from .fetcher import Fetcher
from .models import SerpRequest, SerpResponse
from .orchestrator import run_serp
from .urls import InvalidUrl, validate_search_url

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
    settings: Settings = Depends(get_app_settings),
):
    request_id = str(uuid.uuid4())
    t0 = time.perf_counter()

    def elapsed() -> int:
        return int((time.perf_counter() - t0) * 1000)

    try:
        validate_search_url(req.url)
    except InvalidUrl as e:
        return _error_response(request_id, "invalid_url", str(e), 400, elapsed(), 0)

    outcome = await run_serp(req, fetcher, settings)

    if not outcome.ok:
        log.warning("request_id=%s page=%s classification=%s reason=%s", request_id, outcome.failed_page, outcome.error_code, outcome.error_message)
        return _error_response(request_id, outcome.error_code, outcome.error_message, outcome.status_code, elapsed(), outcome.requests_used, outcome.first)

    for w in outcome.warnings:
        log.warning("request_id=%s parse warning: %s", request_id, w)

    if not req.return_json:
        resp = HTMLResponse(content=outcome.first.html or "")
    else:
        body = SerpResponse(status_code=200, requests_used=outcome.requests_used, elapsed_time=elapsed(), results=outcome.pages)
        resp = JSONResponse(content=body.model_dump())
    _set_debug_headers(resp, request_id, "ok", outcome.first)
    return resp
