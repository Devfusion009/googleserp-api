"""Parse organic web results from inside #rso.

Hook: "a link containing an h3 = organic title" (per the brief). For each such
link we climb to its per-result container - the nearest ancestor carrying a
data-hveid attribute, which every individual #rso item has regardless of type
(plain web result, video result, etc) - then read the rest of that container.

URLs come from ParseContext.links (app/links.py): a direct href is used as-is,
/url?q= is unwrapped, and Google's /goto?url=<token> wrapper is looked up in the
token -> destination map the fetcher resolved through Google's own redirect. The
visible breadcrumb is never used to rebuild a URL - it is often just the domain,
not the destination. A link that can't be resolved leaves url None and records
a gap, which fails the page.
"""
import logging
from dataclasses import dataclass, field

from selectolax.parser import Node

from ..urls import strip_text_fragment
from .context import ParseContext
from .misc import clean_prose, clean_text

log = logging.getLogger("serp.parsers.organic")

CONTENT_WRAPPER_CLASS = "N54PNb"
IGNORE_LINK_ARIA = {"about this result"}


@dataclass
class SubLink:
    title: str
    url: str | None


@dataclass
class OrganicResult:
    url: str | None
    title: str
    content: str | None
    sub_links: list[SubLink] = field(default_factory=list)


def _find_container(title_link: Node) -> Node:
    """Climb from the title <a> to the nearest ancestor with data-hveid - the
    per-item boundary #rso uses for every result type we've seen."""
    node = title_link
    for _ in range(14):
        if node.parent is None:
            break
        node = node.parent
        if node.attributes.get("data-hveid") is not None:
            return node
    return node  # fallback: whatever we reached (logged by the caller if odd)


def _resolve_url(link: Node, ctx: ParseContext, what: str) -> str | None:
    href = link.attributes.get("href")
    url = ctx.links.resolve(href)
    if url is None:
        ctx.gap("organic", f"{what}: {ctx.link_problem(href)}")
    return url


def _is_real_sublink(a: Node) -> bool:
    href = a.attributes.get("href") or ""
    if not href or href.startswith(("#", "javascript:")):
        return False
    aria = (a.attributes.get("aria-label") or "").strip().lower()
    if aria in IGNORE_LINK_ARIA:
        return False
    return bool(a.text(strip=True))


def parse_organic_results(rso: Node, ctx: ParseContext | None = None) -> tuple[list[OrganicResult], list[str]]:
    ctx = ctx if ctx is not None else ParseContext()
    results: list[OrganicResult] = []
    seen_titles_urls: set[tuple[str, str | None]] = set()

    title_links = [a for a in rso.css("a") if a.css_first("h3") is not None]
    for title_link in title_links:
        h3 = title_link.css_first("h3")
        title = clean_text(h3.text(strip=True))
        if not title:
            continue
        href = title_link.attributes.get("href")
        url = ctx.links.resolve(href)
        key = (title, url or href)
        if key in seen_titles_urls:
            continue  # accessibility duplicate of a result we already have
        seen_titles_urls.add(key)
        if url is None:
            ctx.gap("organic", f"result {title[:60]!r}: {ctx.link_problem(href)}")

        container = _find_container(title_link)
        content, sub_links = _parse_body(container, title_link, ctx)
        results.append(OrganicResult(url=url, title=title, content=content, sub_links=sub_links))

    return results, ctx.warnings


def _parse_body(container: Node, title_link: Node, ctx: ParseContext) -> tuple[str | None, list[SubLink]]:
    wrapper = title_link
    for _ in range(10):
        if wrapper is None or wrapper is container.parent:
            wrapper = None
            break
        cls = (wrapper.attributes.get("class") or "").split()
        if CONTENT_WRAPPER_CLASS in cls:
            break
        wrapper = wrapper.parent
    else:
        wrapper = None

    content: str | None = None
    sub_links: list[SubLink] = []

    if wrapper is not None:
        kids = [c for c in wrapper.iter() if c.tag == "div"]
        # kids[0] is the title+cite block (contains title_link); the rest is
        # snippet text and, sometimes, a row of inline sitelink pills.
        body_kids = kids[1:]
        text_parts = []
        for kid in body_kids:
            links = [a for a in kid.css("a") if _is_real_sublink(a)]
            # A "pills row" (sitelinks, jump-to-section links) has several short
            # links and no prose of its own. A single trailing link (e.g. a
            # "Read more" at the end of a truncated snippet) is not one - that
            # whole child is still the snippet paragraph.
            if len(links) >= 2 and kid.css_first("h3") is None:
                for a in links:
                    sub_title = clean_text(a.text(strip=True)) or ""
                    sub_url = strip_text_fragment(_resolve_url(a, ctx, f"sub-link {sub_title[:40]!r}"))
                    sub_links.append(SubLink(title=sub_title, url=sub_url))
            else:
                t = clean_prose(kid.text(separator=" ", strip=True))
                if t:
                    text_parts.append(t)
        content = clean_prose(" ".join(text_parts)) if text_parts else None
    else:
        # No recognizable content wrapper - e.g. Google's "Web Result with Site
        # Links" layout (a table of sitelinks with no real hrefs at all, see
        # README known limitations). Best effort: the container's text minus
        # the title link's own text and the usual chrome around it.
        full = container.text(separator=" ", strip=True)
        title_text = title_link.text(separator=" ", strip=True)
        if full and title_text and full.startswith(title_text):
            remainder = full[len(title_text):]
            for junk in ("About this result",):
                remainder = remainder.replace(junk, " ")
            content = clean_prose(remainder) or None
        if content is None:
            ctx.warnings.append("could not isolate a snippet for this result (unrecognized layout)")

    return content, sub_links
