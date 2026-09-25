"""Domain orchestration: run one /serp request end to end.

No FastAPI/HTTP here - this module returns data (SerpOutcome), never a
Response. main.py turns the outcome into JSON/headers/log lines.
"""
import logging
import math
from dataclasses import dataclass, field

from selectolax.parser import HTMLParser

from .classify import STATUS_FOR, Classification
from .config import Settings
from .fetcher import FetchResult, Fetcher
from .models import PageResult, SerpRequest
from .parsers.registry import PAGE_PARSERS, BlockParser
from .urls import page_url

log = logging.getLogger("serp.orchestrator")

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


def build_page_result(page_num: int, tree: HTMLParser, warnings: list[str], parsers: list[BlockParser] = PAGE_PARSERS) -> PageResult:
    fields: dict = {"page": page_num}
    for block_parser in parsers:
        fields.update(block_parser(tree, warnings))
    return PageResult(**fields)


@dataclass
class SerpOutcome:
    ok: bool
    pages: list[PageResult] = field(default_factory=list)
    first: FetchResult | None = None
    requests_used: int = 0
    warnings: list[str] = field(default_factory=list)
    failed_page: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    status_code: int = 200


async def run_serp(req: SerpRequest, fetcher: Fetcher, settings: Settings) -> SerpOutcome:
    num_pages = max(1, math.ceil(req.results / settings.results_per_page))
    requests_used = 0
    pages: list[PageResult] = []
    first: FetchResult | None = None
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
            return SerpOutcome(
                ok=False, first=first, requests_used=requests_used, failed_page=page_idx + 1,
                error_code=code, error_message=result.reason, status_code=status_code,
            )

        try:
            tree = HTMLParser(result.html or "")
            page_result = build_page_result(page_idx + 1, tree, all_warnings)
        except Exception:
            log.exception("page=%d parse_error", page_idx + 1)
            return SerpOutcome(
                ok=False, first=first, requests_used=requests_used, failed_page=page_idx + 1,
                error_code="parse_error", error_message="failed to parse the page", status_code=502,
            )
        if not page_result.organic:
            # The brief counts a results page with no organic results as degraded,
            # even when the results container itself was present.
            return SerpOutcome(
                ok=False, first=first, requests_used=requests_used, failed_page=page_idx + 1,
                error_code="degraded_page", error_message="page loaded but had zero organic results", status_code=502,
            )
        pages.append(page_result)

    return SerpOutcome(ok=True, pages=pages, first=first, requests_used=requests_used, warnings=all_warnings)
