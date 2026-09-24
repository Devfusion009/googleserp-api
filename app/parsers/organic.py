"""Parse organic web results from inside #rso.

Hook: "a link containing an h3 = organic title" (per the brief). For each such
link we climb to its per-result container - the nearest ancestor carrying a
data-hveid attribute, which every individual #rso item has regardless of type
(plain web result, video result, etc) - then read the rest of that container.

Google renders each result's URL two different ways depending on the query/
session (both seen in real fixtures):
  - a plain href with the real destination already in it (most common), or
  - href="/goto?url=<opaque token>" - a newer click-wrapper we cannot decode
    (doing so would mean reverse-engineering Google's script, which the brief
    forbids). When we see this, we fall back to the visible <cite> breadcrumb
    text (e.g. "https://en.wikipedia.org/ wiki / Apple_Inc") and rebuild a URL
    from it. This is real, on-page text, not a guess - but it is sometimes
    only the site root when Google doesn't show a full breadcrumb, so the
    reconstructed URL can be less precise than the true destination. We log a
    parse warning whenever we fall back to this path.
"""
import logging
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from selectolax.parser import Node

from ..urls import strip_text_fragment, unwrap_google_redirect
from .misc import clean_prose, clean_text, node_text

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


def _breadcrumb_to_url(cite_text: str) -> str | None:
    """"https://host.com/ wiki / Page" (Google's '›'-joined breadcrumb) -> a URL.
    Real visible text, reassembled - not guessed - but can be imprecise if
    Google only showed the bare domain."""
    if "›" not in cite_text:
        return cite_text if cite_text.startswith("http") else None
    parts = [p.strip() for p in cite_text.split("›")]
    domain = parts[0].rstrip("/")
    if not domain.startswith("http"):
        return None
    path = "/".join(p.replace(" ", "") for p in parts[1:] if p)
    return f"{domain}/{path}" if path else domain


def _resolve_url(title_link: Node, warnings: list[str]) -> str | None:
    href = title_link.attributes.get("href") or ""
    if href.startswith("http://") or href.startswith("https://"):
        host = (urlsplit(href).hostname or "").lower()
        if host.endswith("google.com") and urlsplit(href).path == "/url":
            return unwrap_google_redirect(href)
        return href
    if href.startswith("/url?"):
        return unwrap_google_redirect(href, base="https://www.google.com/")
    # An opaque redirect (e.g. /goto?url=...) or something else unresolvable -
    # fall back to the visible cite/breadcrumb text instead of the href.
    cite = title_link.css_first("cite")
    if cite is not None:
        text = clean_text(cite.text(strip=True))
        if text:
            url = _breadcrumb_to_url(text)
            if url:
                warnings.append(f"used visible cite text for url (href was {href[:40]!r})")
                return url
    warnings.append(f"could not resolve a url for this result (href={href[:60]!r})")
    return None


def _is_real_sublink(a: Node) -> bool:
    href = a.attributes.get("href") or ""
    if not href or href.startswith("#") and False:
        return False
    aria = (a.attributes.get("aria-label") or "").strip().lower()
    if aria in IGNORE_LINK_ARIA:
        return False
    return bool(a.text(strip=True))


def parse_organic_results(rso: Node) -> tuple[list[OrganicResult], list[str]]:
    warnings: list[str] = []
    results: list[OrganicResult] = []
    seen_titles_urls: set[tuple[str, str | None]] = set()

    title_links = [a for a in rso.css("a") if a.css_first("h3") is not None]
    for title_link in title_links:
        h3 = title_link.css_first("h3")
        title = clean_text(h3.text(strip=True))
        if not title:
            continue
        url = _resolve_url(title_link, warnings)
        key = (title, url)
        if key in seen_titles_urls:
            continue  # accessibility duplicate of a result we already have
        seen_titles_urls.add(key)

        container = _find_container(title_link)
        content, sub_links = _parse_body(container, title_link, warnings)
        results.append(OrganicResult(url=url, title=title, content=content, sub_links=sub_links))

    return results, warnings


def _parse_body(container: Node, title_link: Node, warnings: list[str]) -> tuple[str | None, list[SubLink]]:
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
                    sub_url = strip_text_fragment(_resolve_url(a, warnings))
                    sub_links.append(SubLink(title=clean_text(a.text(strip=True)) or "", url=sub_url))
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
            warnings.append("could not isolate a snippet for this result (unrecognized layout)")

    return content, sub_links
