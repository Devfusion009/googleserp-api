"""Parse paid text ads from #tads (top) and #bottomads (bottom).

Hook: every ad is a `[data-text-ad]` element (present whether the ad renders or
not - #tads/#bottomads exist on every page but are empty divs when there are no
ads, so an empty result here is normal, not a failure). Unlike organic results,
the ad's own href is already the real destination (no /goto-style wrapper seen
on any ad in the fixtures) - the tracking redirect lives in a separate data-rw
attribute we never need.

Layout inside one `[data-text-ad]` (confirmed against plumber_austin_tx.html):
  child 0 (class "v5yQqb" style): the title link + displayed domain
  child 1: the ad's own snippet text
  child 2 (optional): either a phone-call extension ("Call us ...") - not
    useful data, skipped - or a sitelinks row (class "qmaLCb") with real anchors,
    some direct and some through /aclk?...&adurl=<real_url> (Google's ad click
    tracker; the real URL is the `adurl` query parameter).
"""
import logging
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

from selectolax.parser import Node

from .misc import clean_prose, clean_text

log = logging.getLogger("serp.parsers.ads")

SITELINKS_ROW_CLASS = "qmaLCb"


@dataclass
class SubLink:
    title: str
    url: str | None


@dataclass
class AdResult:
    url: str | None
    title: str
    content: str | None
    sub_links: list[SubLink] = field(default_factory=list)


def _resolve_ad_link(href: str | None) -> str | None:
    if not href:
        return None
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/aclk"):
        qs = parse_qs(urlsplit(href).query)
        adurl = (qs.get("adurl") or [None])[0]
        return adurl or None
    return None


def parse_ads(container: Node | None, warnings: list[str]) -> list[AdResult]:
    """container is #tads or #bottomads (may be None if the page has neither)."""
    if container is None:
        return []
    ads: list[AdResult] = []
    for ad_div in container.css("[data-text-ad]"):
        title_link = ad_div.css_first("a[href]")
        if title_link is None:
            warnings.append("ad block had no title link; skipped")
            continue
        heading = title_link.css_first("[role=heading]")
        title = clean_text((heading or title_link).text(strip=True))
        url = _resolve_ad_link(title_link.attributes.get("href"))
        if not title or not url:
            warnings.append("ad block missing title or url; skipped")
            continue

        row = ad_div.css_first("div.vt6azd, div.xpd") or ad_div
        kids = [c for c in row.iter() if c.tag == "div"]
        content: str | None = None
        sub_links: list[SubLink] = []
        for kid in kids[1:]:
            sitelinks_row = kid if SITELINKS_ROW_CLASS in (kid.attributes.get("class") or "").split() else kid.css_first(f"div.{SITELINKS_ROW_CLASS}")
            if sitelinks_row is not None:
                for a in sitelinks_row.css("a[href]"):
                    text = clean_text(a.text(strip=True))
                    if not text:
                        continue
                    sub_links.append(SubLink(title=text, url=_resolve_ad_link(a.attributes.get("href"))))
            elif content is None:
                text = clean_prose(kid.text(separator=" ", strip=True))
                if text and "Call us" not in text[:10]:
                    content = text

        ads.append(AdResult(url=url, title=title, content=content, sub_links=sub_links))
    return ads
