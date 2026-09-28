"""Domain orchestration: run one /serp request end to end.

No FastAPI/HTTP here - this module returns data (SerpOutcome), never a
Response. main.py turns the outcome into JSON/headers/log lines.
"""
import logging
import math
from collections import Counter
from dataclasses import dataclass, field

from selectolax.parser import HTMLParser

from .classify import STATUS_FOR, AioState, Classification
from .config import Settings
from .fetcher import FetchResult, Fetcher
from .models import PageResult, SerpRequest
from .links import LinkMap
from .parsers.context import Gap, ParseContext
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


def build_page_result(page_num: int, tree: HTMLParser, ctx: ParseContext, parsers: list[BlockParser] = PAGE_PARSERS) -> PageResult:
    fields: dict = {"page": page_num}
    for block_parser in parsers:
        fields.update(block_parser(tree, ctx))
    return PageResult(**fields)


def completeness_error(gaps: list[Gap]) -> tuple[str, str] | None:
    """(error_code, message) when the page was only partly extracted, else None.

    An incomplete extraction is never a valid result. Unresolved result/ad links
    are parse_error; an AI Overview gap (a source without its destination, or no
    sources) is aio_incomplete. Both use codes from the agreed list."""
    if not gaps:
        return None
    links = [g for g in gaps if g.field != "ai_overview"]
    aio = [g for g in gaps if g.field == "ai_overview"]
    code = "parse_error" if links else "aio_incomplete"
    parts = []
    for field_name, group in (("result links", links), ("AI Overview", aio)):
        if group:
            shown = "; ".join(g.reason for g in group[:3]) + (f"; +{len(group) - 3} more" if len(group) > 3 else "")
            parts.append(f"{len(group)} incomplete {field_name}: {shown}")
    return code, "incomplete extraction - " + " | ".join(parts)


@dataclass
class SerpOutcome:
    ok: bool
    pages: list[PageResult] = field(default_factory=list)
    first: FetchResult | None = None
    requests_used: int = 0
    usage: dict[str, int] = field(default_factory=dict)  # requests by kind, all pages
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
    usage: Counter = Counter()

    for page_idx in range(num_pages):
        url = page_url(req.url, page_idx)
        result = await fetcher.fetch(url, req.country, req.language)
        requests_used += result.requests_used
        usage.update(result.usage)
        if page_idx == 0:
            first = result

        def fail(code: str, message: str, status_code: int) -> SerpOutcome:
            return SerpOutcome(
                ok=False, first=first, requests_used=requests_used, usage=dict(usage), failed_page=page_idx + 1,
                error_code=code, error_message=message, status_code=status_code,
            )

        if result.classification is not Classification.ok:
            code = ERROR_CODE_FOR.get(result.classification, "network_error")
            return fail(code, result.reason, STATUS_FOR.get(result.classification, 502))

        try:
            tree = HTMLParser(result.html or "")
            ctx = ParseContext(links=LinkMap(resolved=result.links))
            page_result = build_page_result(page_idx + 1, tree, ctx)
            all_warnings.extend(ctx.warnings)
        except Exception:
            log.exception("page=%d parse_error", page_idx + 1)
            return fail("parse_error", "failed to parse the page", 502)
        if not page_result.organic:
            # The brief counts a results page with no organic results as degraded,
            # even when the results container itself was present.
            return fail("degraded_page", "page loaded but had zero organic results", 502)
        incomplete = completeness_error(ctx.gaps)
        if incomplete is not None:
            code, message = incomplete
            if code == "aio_incomplete":
                result.aio_state = AioState.incomplete
            return fail(code, message, STATUS_FOR[Classification(code)])
        pages.append(page_result)

    return SerpOutcome(ok=True, pages=pages, first=first, requests_used=requests_used, usage=dict(usage), warnings=all_warnings)
