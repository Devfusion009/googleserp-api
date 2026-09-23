"""Page classification. Pure functions of (final URL, HTML) - no browser needed.

The AI Overview hooks here are starting points; Phase 3 confirms them against
real fixture pages and the README documents the final rules.
"""
import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser, Node


class Classification(str, Enum):
    ok = "ok"
    blocked_captcha = "blocked_captcha"
    consent_wall = "consent_wall"
    degraded_page = "degraded_page"
    aio_incomplete = "aio_incomplete"
    parse_error = "parse_error"
    timeout = "timeout"
    network_error = "network_error"
    invalid_url = "invalid_url"


class AioState(str, Enum):
    absent = "absent"
    complete = "complete"
    incomplete = "incomplete"


STATUS_FOR = {
    Classification.ok: 200,
    Classification.blocked_captcha: 429,
    Classification.consent_wall: 502,
    Classification.degraded_page: 502,
    Classification.aio_incomplete: 502,
    Classification.parse_error: 502,
    Classification.timeout: 504,
    Classification.network_error: 502,
    Classification.invalid_url: 400,
}

CAPTCHA_TEXT = ("unusual traffic from your computer network", "our systems have detected unusual traffic")
CONSENT_TEXT = ("before you continue to google", "before you continue")
JS_REQUIRED_TEXT = (
    "turn on javascript to keep searching",
    "please enable javascript",
    "javascript is disabled",
    "if you're having trouble accessing google search",
    "please click here if you are not redirected",
)
BASIC_HTML_TEXT = ("switch to the basic version", "you're using the basic version", "basic html version")

# Text Google shows inside an AI Overview while generating or when it failed.
AIO_LOADING_TEXT = ("generating", "searching", "thinking")
AIO_FAILED_TEXT = (
    "an ai overview is not available for this search",
    "can't generate an ai overview right now",
    "ai overview is not available",
)


@dataclass
class PageVerdict:
    classification: Classification
    reason: str
    aio_state: AioState = AioState.absent


def _visible_text(tree: HTMLParser) -> str:
    body = tree.body
    if body is None:
        return ""
    clone = HTMLParser(body.html or "")
    clone.strip_tags(["script", "style", "noscript", "template"])
    text = clone.body.text(separator=" ") if clone.body else ""
    return re.sub(r"\s+", " ", text).strip().lower()


def find_aio_root(tree: HTMLParser) -> Node | None:
    """The AI Overview block: the nearest large container around a heading whose
    text is exactly 'AI Overview'. Confirmed/refined against fixtures in Phase 3."""
    for h in tree.css("h1, h2, div[role=heading], span[role=heading]"):
        if (h.text(strip=True) or "").lower() == "ai overview":
            node = h
            # climb until the container holds more than the heading itself
            for _ in range(8):
                if node.parent is None:
                    break
                node = node.parent
                if len(node.text(strip=True)) > 200:
                    return node
            return node
    return None


def aio_state(tree: HTMLParser) -> tuple[AioState, str]:
    root = find_aio_root(tree)
    if root is None:
        return AioState.absent, "no AI Overview heading"
    text = re.sub(r"\s+", " ", root.text(separator=" ")).strip().lower()
    for t in AIO_FAILED_TEXT:
        if t in text:
            return AioState.incomplete, f"AI Overview shows '{t}'"
    body = text.replace("ai overview", "", 1).strip()
    if len(body) < 80 and any(t in body for t in AIO_LOADING_TEXT):
        return AioState.incomplete, "AI Overview still loading"
    if len(body) < 40:
        return AioState.incomplete, f"AI Overview has only {len(body)} chars of text"
    return AioState.complete, "AI Overview text present"


def classify_page(final_url: str, html: str, organic_count: int | None = None) -> PageVerdict:
    parts = urlsplit(final_url or "")
    host = (parts.hostname or "").lower()
    tree = HTMLParser(html or "")
    text = _visible_text(tree)

    if parts.path.startswith("/sorry/"):
        return PageVerdict(Classification.blocked_captcha, "redirected to /sorry/ (unusual traffic)")
    if any(t in text for t in CAPTCHA_TEXT):
        return PageVerdict(Classification.blocked_captcha, "'unusual traffic' message on page")
    if tree.css_first("div.g-recaptcha, iframe[src*='recaptcha']") is not None and tree.css_first("#rso") is None:
        return PageVerdict(Classification.blocked_captcha, "reCAPTCHA widget on page")

    if host == "consent.google.com":
        return PageVerdict(Classification.consent_wall, "redirected to consent.google.com")
    if tree.css_first("form[action*='consent.google.com']") is not None or any(text.startswith(t) or f" {t}" in text[:400] for t in CONSENT_TEXT):
        return PageVerdict(Classification.consent_wall, "'Before you continue' consent page")

    if any(t in text for t in JS_REQUIRED_TEXT) and tree.css_first("#rso") is None:
        return PageVerdict(Classification.degraded_page, "JavaScript-required notice")
    if any(t in text for t in BASIC_HTML_TEXT):
        return PageVerdict(Classification.degraded_page, "basic HTML version of Google")
    if tree.css_first("#search") is None and tree.css_first("#rso") is None:
        return PageVerdict(Classification.degraded_page, "results container (#search/#rso) missing")
    if organic_count is not None and organic_count == 0:
        return PageVerdict(Classification.degraded_page, "zero organic results")

    state, why = aio_state(tree)
    if state is AioState.incomplete:
        return PageVerdict(Classification.aio_incomplete, why, state)
    return PageVerdict(Classification.ok, "results page" + (" with AI Overview" if state is AioState.complete else ""), state)
