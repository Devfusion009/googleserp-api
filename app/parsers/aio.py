"""Parse the AI Overview block into {intro, sections, sources}.

Hooks used (confirmed against saved fixtures, see README "How AI Overview parsing
works" for the human-readable version of these rules):
  - The block itself: found the same way classify.find_aio_root does (climb from the
    "AI Overview" heading until the enclosing element's text is substantial).
  - Section headings: any descendant with role=heading and aria-level="3".
  - Plain paragraphs (the intro, and the closing "If you'd like..." line): elements
    with class "n6owBd" - these hold flowing prose, not bullets.
  - Bullet lines: plain <li> elements once we're inside the response body.
  - The sources panel: a <li class="h7wxwc"> per unique source, each holding one
    <a class="vIWmYe"> (title in aria-label, href is the real destination - no
    Google redirect wrapper on this link) plus ".gpZmoc" (title text again) and
    ".hxIQcc" (snippet). This panel always comes after the response's own text in
    document order, so it also marks where we stop reading intro/section text -
    the one paragraph Google adds after the last heading ("If you'd like to know
    more, ask about X or Y") is real response text and stays attached to the last
    section; everything from the sources panel onward (including its several
    hidden accessibility copies of the same cards) is dropped from intro/sections.
Google renders a hidden aria-only duplicate right next to almost everything here;
dedupe_consecutive() drops the repeat.
"""
import logging
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser, Node

from ..urls import strip_text_fragment, unwrap_google_redirect
from .misc import clean_prose, clean_text, dedupe_consecutive, node_text

log = logging.getLogger("serp.parsers.aio")

SOURCE_ITEM_CLASS = "h7wxwc"
SOURCE_LINK_CLASS = "vIWmYe"
SOURCE_TITLE_CLASS = "gpZmoc"
SOURCE_SNIPPET_CLASS = "hxIQcc"
PARAGRAPH_CLASS = "n6owBd"
# The small inline citation pill Google drops after a sentence/bullet (e.g. a
# favicon + "Cloudflare +1"). It carries no prose of its own, so it's stripped
# before reading paragraph/bullet text - otherwise it reads as junk trailing text.
CITATION_BADGE_CLASS = "WBgIic"


@dataclass
class AioSection:
    title: str
    text: str = ""
    text_parts: list[str] = field(default_factory=list, repr=False, compare=False)


@dataclass
class AioSource:
    title: str | None
    url: str
    snippet: str | None


@dataclass
class ParsedAio:
    intro: list[str] = field(default_factory=list)
    sections: list[AioSection] = field(default_factory=list)
    sources: list[AioSource] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _has_class(node: Node, cls: str) -> bool:
    classes = (node.attributes.get("class") or "").split()
    return cls in classes


def _is_heading3(node: Node) -> bool:
    return node.attributes.get("role") == "heading" and node.attributes.get("aria-level") == "3"


def _resolve_source_url(href: str | None) -> str | None:
    if not href:
        return None
    url = unwrap_google_redirect(href) if href.startswith("/") else href
    url = strip_text_fragment(url)
    if not url:
        return None
    host = (urlsplit(url).hostname or "").lower()
    if host == "google.com" or host.endswith(".google.com"):
        return None
    return url


def _parse_sources(root: Node, warnings: list[str]) -> list[AioSource]:
    sources: list[AioSource] = []
    seen: set[str] = set()
    for item in root.css(f"li.{SOURCE_ITEM_CLASS}"):
        link = item.css_first(f"a.{SOURCE_LINK_CLASS}")
        url = _resolve_source_url(link.attributes.get("href")) if link else None
        if not url:
            warnings.append("aio source item had no resolvable url; skipped")
            continue
        if url in seen:
            continue
        seen.add(url)
        title = node_text(item.css_first(f".{SOURCE_TITLE_CLASS}"))
        snippet = node_text(item.css_first(f".{SOURCE_SNIPPET_CLASS}"))
        sources.append(AioSource(title=title, url=url, snippet=snippet))
    return sources


def parse_aio(root: Node) -> ParsedAio:
    """root is the AI Overview container, as returned by classify.find_aio_root."""
    warnings: list[str] = []
    sources = _parse_sources(root, warnings)

    for badge in root.css(f".{CITATION_BADGE_CLASS}"):
        badge.remove()

    intro_parts: list[str] = []
    sections: list[AioSection] = []
    current: AioSection | None = None

    def emit(text: str | None) -> None:
        nonlocal current
        text = clean_prose(text)
        if not text:
            return
        if current is None:
            intro_parts.append(text)
        else:
            current.text_parts.append(text)

    for node in root.traverse():
        if node.tag == "-text":
            continue
        if node.tag in ("ul", "ol") and node.css_first(f"li.{SOURCE_ITEM_CLASS}"):
            # reached the sources panel - nothing after this point is response text.
            break
        if node.attributes.get("role") == "heading":
            level = node.attributes.get("aria-level")
            if level == "3":
                title = clean_text(node.text(strip=True))
                if title:
                    current = AioSection(title=title)
                    sections.append(current)
                continue
            if level == "2":
                continue  # the "AI Overview" title itself
        if _has_class(node, PARAGRAPH_CLASS):
            emit(node.text(separator=" ", strip=True))
            continue
        if node.tag == "li":
            # a bullet in the response body (not one of the source cards - those
            # were already excluded by the `break` above once we hit the panel).
            emit("- " + (node.text(separator=" ", strip=True) or ""))
            continue

    for section in sections:
        section.text = "\n".join(dedupe_consecutive(section.text_parts))

    intro = dedupe_consecutive(intro_parts)

    if not intro and not sections:
        warnings.append("AI Overview root had no readable intro/sections text")

    for w in warnings:
        log.warning(w)

    return ParsedAio(intro=intro, sections=[s for s in sections if s.text], sources=sources, warnings=warnings)
