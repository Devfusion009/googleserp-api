"""Parse the AI Overview block into {intro, sections, sources}.

Hooks used (confirmed against saved fixtures, see README "How AI Overview parsing
works" for the human-readable version of these rules):
  - The block itself: found the same way classify.find_aio_root does (climb from the
    "AI Overview" heading until the enclosing element's text is substantial).
  - Section headings: any descendant with role=heading and aria-level="3".
  - Plain paragraphs (the intro, and the closing "If you'd like..." line): elements
    with class "n6owBd" - these hold flowing prose, not bullets.
  - Bullet lines: plain <li> elements once we're inside the response body.
  - The sources panel: a <li class="h7wxwc"> per source card, each holding one
    <a class="vIWmYe"> (title in aria-label; href is either the real destination
    or Google's /goto?url=<token> wrapper, resolved through ParseContext.links -
    see app/links.py) plus ".gpZmoc" (title text again) and ".hxIQcc" (snippet).
    A card whose destination can't be resolved is a gap (the page fails as
    aio_incomplete), and so is an AI Overview with no source cards at all or no
    readable text. This panel always comes after the response's own text in
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

from selectolax.parser import HTMLParser, Node

from ..urls import strip_text_fragment
from .context import ParseContext
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


def _is_product_card(link: Node | None, href: str | None) -> bool:
    """Google's shopping card in the sources panel: no href, role=button and a
    product cluster id (data-cid). Anything else without a usable link is a
    citation we failed to resolve."""
    return link is not None and not href and link.attributes.get("role") == "button" and bool(link.attributes.get("data-cid"))


def _parse_sources(root: Node, ctx: ParseContext, warnings: list[str]) -> list[AioSource]:
    sources: list[AioSource] = []
    seen: set[str] = set()
    for item in root.css(f"li.{SOURCE_ITEM_CLASS}"):
        link = item.css_first(f"a.{SOURCE_LINK_CLASS}")
        href = link.attributes.get("href") if link else None
        if _is_product_card(link, href):
            # A shopping card: a button that opens Google's product viewer in the
            # page. It is UI, not a citation - there is no page it cites.
            warnings.append(f"aio product card {node_text(item.css_first(f'.{SOURCE_TITLE_CLASS}')) or '?'!r} is a shopping element, not a citation; not listed")
            continue
        # Redirect wrappers (/goto, /url?q=) are resolved; a citation of a Google
        # page (e.g. Google Flights) is a genuine source and stays. A citation
        # that can't be resolved is a gap, never silently dropped.
        url = strip_text_fragment(ctx.links.resolve(href))
        if not url:
            ctx.gap("ai_overview", f"source card {node_text(item.css_first(f'.{SOURCE_TITLE_CLASS}')) or '?'!r}: {ctx.link_problem(href)}")
            continue
        if url in seen:
            continue
        seen.add(url)
        title = node_text(item.css_first(f".{SOURCE_TITLE_CLASS}"))
        snippet = node_text(item.css_first(f".{SOURCE_SNIPPET_CLASS}"))
        sources.append(AioSource(title=title, url=url, snippet=snippet))
    return sources


def parse_aio(root: Node, ctx: ParseContext | None = None) -> ParsedAio:
    """root is the AI Overview container, as returned by classify.find_aio_root."""
    ctx = ctx if ctx is not None else ParseContext()
    warnings: list[str] = []
    has_cards = root.css_first(f"li.{SOURCE_ITEM_CLASS}") is not None
    sources = _parse_sources(root, ctx, warnings)

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
        # The block is on the page; returning ai_overview: null would pass it off
        # as a page without one.
        ctx.gap("ai_overview", "AI Overview text could not be read")
    elif not has_cards:
        ctx.gap("ai_overview", "no source cards found")

    for w in warnings:
        log.warning(w)
    ctx.warnings.extend(warnings)

    return ParsedAio(intro=intro, sections=[s for s in sections if s.text], sources=sources, warnings=warnings)
