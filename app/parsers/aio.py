"""Parse the AI Overview block into {intro, sections, sources}.

Hooks used (confirmed against saved fixtures, see README "How AI Overview parsing
works" for the human-readable version of these rules):
  - The block itself: found the same way classify.find_aio_root does (climb from the
    "AI Overview" heading until the enclosing element's text is substantial).
  - Section headings: any descendant with role=heading and aria-level="3".
  - Plain paragraphs (the intro, and the closing "If you'd like..." line): elements
    with class "n6owBd" - these hold flowing prose, not bullets.
  - Bullet lines: plain <li> elements once we're inside the response body. A bullet
    with a sub-list (e.g. "GEICO" over "Average cost: ..." / "Best for: ...") is read
    without its sub-list, and each sub-bullet is indented two spaces per level, so
    the sub-bullets are written once and stay under their parent.
  - The sources panel: an <li> per source card (class "h7wxwc", renamed "Ioqnib" in pages
    from 2026-10-07; other <li>s around the same links, e.g. "Gzwrb" / "Ndm2cf", are
    hidden citation pop-ups, not the panel), each holding one
    <a class="vIWmYe"> (title in aria-label; href is either the real destination
    or Google's /goto?url=<token> wrapper, resolved through ParseContext.links -
    see app/links.py) plus ".gpZmoc" (title text again) and ".hxIQcc" (snippet).
    A card whose destination can't be resolved is a gap (the page fails as
    aio_incomplete), and so is an AI Overview with no readable text, or with links shaped
    like source cards in a layout we don't know.
  - Inline citations (no panel needed, seen on 'chase bank login'): the response text links
    its sources itself - a plain <a> inside a paragraph/bullet (title = link text) and a
    citation chip <span class="WBgIic"> holding <a class="PMDqCb"> (title in aria-label;
    "+N" in ".OkUHJe" = N more sources behind the chip, only in the DOM after a click).
    These are sources too, listed after the panel cards, deduped by URL, same /goto
    resolution and gap rules. Links straight to a Google page (Learn more, policies, the
    shopping product viewer) are UI, not citations. Only an overview with neither panel nor any citation is complete
    with sources: [] (and a warning); citation markup with no source read is a gap.
    The sources panel always comes after the response's own text in
    document order, so it also marks where we stop reading intro/section text -
    the one paragraph Google adds after the last heading ("If you'd like to know
    more, ask about X or Y") is real response text and stays attached to the last
    section; everything from the sources panel onward (including its several
    hidden accessibility copies of the same cards) is dropped from intro/sections.
  - The newer sources panel (seen from 2026-10-07): a div[role=list] of div[role=listitem]
    cards, each with one <a class="POYEld"> (aria-label "<title>. Opens in new tab."; href
    as above), the title in ".vFyWT" and the snippet in ".BEwxRe". Same rules as the old
    cards; either layout counts as the panel.
Google renders a hidden aria-only duplicate right next to almost everything here;
dedupe_consecutive() drops the repeat.
"""
import logging
from dataclasses import dataclass, field

from selectolax.parser import HTMLParser, Node

from urllib.parse import urlsplit

from ..links import _is_google_host
from ..urls import strip_text_fragment
from .context import ParseContext
from .misc import clean_prose, clean_text, dedupe_consecutive, node_text

log = logging.getLogger("serp.parsers.aio")

SOURCE_ITEM_SELECTOR = "li.h7wxwc, li.Ioqnib"
SOURCE_LINK_CLASS = "vIWmYe"
SOURCE_TITLE_CLASS = "gpZmoc"
SOURCE_SNIPPET_CLASS = "hxIQcc"
PARAGRAPH_CLASS = "n6owBd"
# The small inline citation pill Google drops after a sentence/bullet (e.g. a
# favicon + "Cloudflare +1"). It carries no prose of its own, so it's stripped
# before reading paragraph/bullet text - otherwise it reads as junk trailing text.
CITATION_BADGE_CLASS = "WBgIic"
# Inline citation chip link (see module docstring) and the "+N" count of its hidden extras.
CHIP_LINK_CLASS = "PMDqCb"
CHIP_EXTRA_CLASS = "OkUHJe"
# The newer sources panel (see module docstring).
CARD2_LINK_CLASS = "POYEld"
CARD2_TITLE_CLASS = "vFyWT"
CARD2_SNIPPET_CLASS = "BEwxRe"
OPENS_IN_NEW_TAB = ". Opens in new tab."
# Every source card link so far (both layouts) carries this aria-label; inline citation
# chips and the overview's own links do not.
CARD_LINK_HINT = 'a[aria-label$="Opens in new tab."]'


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


def _own_text(li: Node) -> str:
    """A bullet's text without its nested lists (read separately, as sub-bullets)."""
    if li.css_first("ul, ol") is None:
        return li.text(separator=" ", strip=True)
    copy = HTMLParser(li.html or "").css_first("li")
    for sub in copy.css("ul, ol"):
        sub.decompose()
    return copy.text(separator=" ", strip=True)


def _list_depth(li: Node, root: Node) -> int:
    """How many bullets `li` is nested in, inside the AI Overview block."""
    depth, node = 0, li.parent
    while node is not None and node is not root:
        if node.tag == "li":
            depth += 1
        node = node.parent
    return depth


def _is_product_card(link: Node | None, href: str | None) -> bool:
    """Google's shopping card in the sources panel: no href (missing, or the literal
    string "undefined" in pages from 2026-10-10), role=button and a product cluster id
    (data-cid). Anything else without a usable link is a citation we failed to resolve."""
    return (link is not None and (not href or href == "undefined") and link.attributes.get("role") == "button"
            and bool(link.attributes.get("data-cid")))


def _card_title(item: Node, link: Node | None, newer: bool) -> str | None:
    if not newer:
        return node_text(item.css_first(f".{SOURCE_TITLE_CLASS}"))
    title = node_text(item.css_first(f".{CARD2_TITLE_CLASS}"))
    if not title and link is not None:
        title = clean_text((link.attributes.get("aria-label") or "").removesuffix(OPENS_IN_NEW_TAB)) or None
    return title


def _source_cards(root: Node) -> list[tuple[Node, Node | None, bool]]:
    """(card, its link, newer layout?) for every source card, old and newer layout, in page order."""
    cards = [(item, item.css_first(f"a.{SOURCE_LINK_CLASS}"), False) for item in root.css(SOURCE_ITEM_SELECTOR)]
    for item in root.css("[role=listitem]"):
        link = item.css_first(f"a.{CARD2_LINK_CLASS}")
        if link is not None:
            cards.append((item, link, True))
    return cards


def _is_sources_panel(node: Node) -> bool:
    if node.tag in ("ul", "ol") and node.css_first(SOURCE_ITEM_SELECTOR):
        return True
    return node.attributes.get("role") == "list" and node.css_first(f"a.{CARD2_LINK_CLASS}") is not None


def _parse_sources(root: Node, ctx: ParseContext, warnings: list[str]) -> list[AioSource]:
    sources: list[AioSource] = []
    seen: set[str] = set()
    _read_cards(root, ctx, warnings, sources, seen)
    if not _source_cards(root):
        # No panel: the response text and its chips are the only place sources are named.
        # With a panel they only repeat its cards.
        sources.extend(_parse_citations(root, ctx, warnings, seen))
    return sources


def _read_cards(root: Node, ctx: ParseContext, warnings: list[str], sources: list[AioSource], seen: set[str]) -> None:
    for item, link, newer in _source_cards(root):
        href = link.attributes.get("href") if link else None
        if _is_product_card(link, href):
            # A shopping card: a button that opens Google's product viewer in the
            # page. It is UI, not a citation - there is no page it cites.
            warnings.append(f"aio product card {_card_title(item, link, newer) or '?'!r} is a shopping element, not a citation; not listed")
            continue
        # Redirect wrappers (/goto, /url?q=) are resolved; a citation of a Google
        # page (e.g. Google Flights) is a genuine source and stays. A citation
        # that can't be resolved is a gap, never silently dropped.
        url = strip_text_fragment(ctx.links.resolve(href))
        if not url:
            ctx.gap("ai_overview", f"source card {_card_title(item, link, newer) or '?'!r}: {ctx.link_problem(href)}")
            continue
        if url in seen:
            continue
        seen.add(url)
        title = _card_title(item, link, newer)
        snippet = node_text(item.css_first(f".{CARD2_SNIPPET_CLASS if newer else SOURCE_SNIPPET_CLASS}"))
        sources.append(AioSource(title=title, url=url, snippet=snippet))


def _is_google_ui_link(href: str | None) -> bool:
    """A link straight to a Google page ("Learn more", policies). /goto and /url?q= wrappers
    are citations, as are relative links that are not Google hosts."""
    if not href or not href.startswith(("http://", "https://", "/")) or href.startswith("//"):
        return False
    parts = urlsplit(href)
    on_google = not parts.netloc or _is_google_host(parts.hostname or "")  # relative = Google's own
    return on_google and parts.path not in ("/goto", "/url")


def _citation_links(root: Node) -> list[tuple[Node, str | None]]:
    """(link, title) for each inline citation: chip links, then plain links in the response
    text (paragraphs and bullets), in page order. Source-card links are not included."""
    found: list[tuple[Node, str | None]] = []
    seen_nodes: set[int] = set()
    for node in root.traverse():
        if node.tag != "a" or node.mem_id in seen_nodes:
            continue
        if _has_class(node, SOURCE_LINK_CLASS) or _has_class(node, CARD2_LINK_CLASS):
            continue
        href = node.attributes.get("href")
        if not href:
            continue
        if _has_class(node, CHIP_LINK_CLASS):  # a chip is a citation whatever host it names (e.g. Google Play)
            seen_nodes.add(node.mem_id)
            found.append((node, clean_text(node.attributes.get("aria-label") or "") or None))
            continue
        if _is_google_ui_link(href):
            continue
        parent, in_text = node.parent, False
        while parent is not None and parent is not root:
            if _has_class(parent, PARAGRAPH_CLASS) or parent.tag == "li":
                in_text = True
                break
            parent = parent.parent
        if in_text:
            seen_nodes.add(node.mem_id)
            found.append((node, node_text(node)))
    return found


def _parse_citations(root: Node, ctx: ParseContext, warnings: list[str], seen: set[str]) -> list[AioSource]:
    sources: list[AioSource] = []
    for link, title in _citation_links(root):
        url = strip_text_fragment(ctx.links.resolve(link.attributes.get("href")))
        if not url:
            ctx.gap("ai_overview", f"citation {title or '?'!r}: {ctx.link_problem(link.attributes.get('href'))}")
            continue
        if url in seen:
            continue
        seen.add(url)
        sources.append(AioSource(title=title, url=url, snippet=None))
    for extra in root.css(f".{CHIP_EXTRA_CLASS}"):
        count = (clean_text(extra.text(strip=True)) or "").lstrip("+")
        if count.isdigit():
            warnings.append(f"AI Overview citation chip has {count} more source(s) behind it, not expanded")
    return sources


def parse_aio(root: Node, ctx: ParseContext | None = None) -> ParsedAio:
    """root is the AI Overview container, as returned by classify.find_aio_root."""
    ctx = ctx if ctx is not None else ParseContext()
    warnings: list[str] = []
    has_cards = bool(_source_cards(root))
    has_citations = bool(_citation_links(root))
    has_chip_links = root.css_first(f".{CITATION_BADGE_CLASS} a") is not None  # the badges are removed below
    sources = _parse_sources(root, ctx, warnings)

    for badge in root.css(f".{CITATION_BADGE_CLASS}"):
        badge.remove()

    intro_parts: list[str] = []
    sections: list[AioSection] = []
    current: AioSection | None = None

    def emit(text: str | None, prefix: str = "") -> None:
        nonlocal current
        text = clean_prose(text)
        if not text:
            return
        text = prefix + text
        if current is None:
            intro_parts.append(text)
        else:
            current.text_parts.append(text)

    for node in root.traverse():
        if node.tag == "-text":
            continue
        if _is_sources_panel(node):
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
            emit(_own_text(node), "  " * _list_depth(node, root) + "- ")
            continue

    for section in sections:
        section.text = "\n".join(dedupe_consecutive(section.text_parts))

    intro = dedupe_consecutive(intro_parts)

    if not intro and not sections:
        # The block is on the page; returning ai_overview: null would pass it off
        # as a page without one.
        ctx.gap("ai_overview", "AI Overview text could not be read")
    elif not has_cards:
        if root.css_first(CARD_LINK_HINT):
            # Links shaped like source cards are there, but in no layout we know: a gap,
            # so a new layout never passes off as an overview without sources.
            ctx.gap("ai_overview", "source cards present but not recognised (unknown layout)")
        elif not has_citations:
            if has_chip_links:
                # Citation chips whose link is in no shape we read: a gap, never an empty list.
                ctx.gap("ai_overview", "citation chips present but not recognised (unknown layout)")
            else:
                # No source panel and no citation at all: nothing is dropped.
                warnings.append("AI Overview shows no source cards")

    for w in warnings:
        log.warning(w)
    ctx.warnings.extend(warnings)

    return ParsedAio(intro=intro, sections=[s for s in sections if s.text], sources=sources, warnings=warnings)
