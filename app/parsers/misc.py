"""Small shared parsing helpers used by more than one parser module, plus the
misc top-level fields: number_of_results, suggestions, corrections.
"""
import logging
import re
from urllib.parse import parse_qs, urlsplit

from selectolax.parser import Node

log = logging.getLogger("serp.parsers.misc")

NUMBER_OF_RESULTS_RE = re.compile(r"([\d,]+)\s+results?", re.IGNORECASE)

WHITESPACE_RE = re.compile(r"[ \t]+")


def clean_text(s: str | None) -> str | None:
    """Collapse internal whitespace/newlines from selectolax's text(), keep single spaces."""
    if not s:
        return None
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s*\n\s*", " ", s)
    s = WHITESPACE_RE.sub(" ", s).strip()
    return s or None


def clean_prose(s: str | None) -> str | None:
    """clean_text(), plus fix the stray spaces left by joining sibling text nodes
    with separator=" " (e.g. "waves ." or "( cache )" -> "waves." / "(cache)")."""
    s = clean_text(s)
    if not s:
        return None
    # Note: '.' is deliberately excluded here. Stripping the space before it
    # would turn "like .com" into "like.com", which reads as a real (wrong)
    # domain - worse than leaving a stray space before a sentence-ending period.
    s = re.sub(r"\s+([,;:!?)’])", r"\1", s)
    s = re.sub(r"([(“])\s+", r"\1", s)
    return s


def node_text(node: Node | None, separator: str = " ") -> str | None:
    if node is None:
        return None
    return clean_text(node.text(separator=separator, strip=True))


def parse_number_of_results(tree) -> int | None:
    """"About 129,000,000 results (0.21s)" -> 129000000. None if Google doesn't
    show a count (normal, not a failure - some queries just don't get one)."""
    node = tree.css_first("#result-stats")
    text = node_text(node) if node else None
    if not text:
        return None
    m = NUMBER_OF_RESULTS_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _decoded_query_param(href: str | None) -> str | None:
    """Pull the literal q= value out of a Google search-again link. More
    reliable than the visible link text, which often has no space between a
    bolded query term and the rest (e.g. "Coffee shops near seattlewashington")."""
    if not href:
        return None
    qs = parse_qs(urlsplit(href).query)
    q = (qs.get("q") or [None])[0]
    return q.replace("+", " ").strip() if q else None


def parse_suggestions(tree) -> list[str]:
    """"Related searches" / "People also search for" chips at the bottom of the
    page. Scoped to #botstuff (where that block lives) and to the LAST match,
    since a knowledge panel can have its own earlier "People also search for"
    carousel of related entities - that one has no query-search links, but we
    still don't want to risk matching its heading instead."""
    scope = tree.css_first("#botstuff") or tree
    header = None
    for node in scope.css("span, div, h3"):
        t = node.text(strip=True)
        if t in ("Related searches", "People also search for"):
            header = node
    if header is None:
        return []
    container = header
    for _ in range(6):
        if container.parent is None:
            break
        container = container.parent
        links = [a for a in container.css("a[href]") if a.text(strip=True)]
        if 2 <= len(links) <= 12:
            out = []
            for a in links:
                q = _decoded_query_param(a.attributes.get("href")) or clean_text(a.text(strip=True))
                if q:
                    out.append(q)
            return out
    return []


def parse_corrections(tree) -> list[str]:
    """"Did you mean", "Showing results for", "Search instead for" -> the corrected
    query text, else []. (Not exercised by any fixture we've captured yet - no
    misspelled query in the corpus - so this is best-effort; flag if it misfires.)"""
    for label in ("Showing results for", "Search instead for", "Did you mean"):
        for node in tree.css("a, span"):
            t = node.text(strip=True)
            if t.startswith(label):
                link = node if node.tag == "a" else node.css_first("a")
                if link is None:
                    continue
                q = _decoded_query_param(link.attributes.get("href")) or clean_text(link.text(strip=True))
                if q:
                    log.info("correction detected (%s): %r", label, q)
                    return [q]
    return []


def dedupe_consecutive(items: list[str]) -> list[str]:
    """Drop an item that is an exact repeat of the one immediately before it.

    Google frequently renders a hidden aria-only copy of a heading/paragraph/bullet
    right next to the visible one; both end up adjacent in document order.
    """
    out: list[str] = []
    for it in items:
        if out and out[-1] == it:
            continue
        out.append(it)
    return out
