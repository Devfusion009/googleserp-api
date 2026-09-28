"""Turning a link on the results page into its real destination.

Since 26 Aug 2026 Google serves signed-out result links as /goto?url=<token>
(organic results, sitelinks, AI Overview sources, sometimes more). The token is
encrypted and different on every render - the same URL gets a new token each
time it appears, even within one page - so it can't be decoded or looked up
from the page. What the page does carry for these links is at most the domain
(breadcrumb, favicon records), which is not the destination.

The one source of truth is Google's own redirect: GET /goto?url=<token> answers
302 with the destination in Location. The fetcher makes that request (redirect
not followed - the destination site is never contacted) for exactly the tokens
the parsers need, and the parsers get a token -> URL map through LinkMap. A
token with no entry stays unresolved: url None plus a gap, which fails the page
(orchestrator) - it is never replaced by a guess.
"""
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import parse_qs, urljoin, urlsplit

from .urls import unwrap_google_redirect

GOOGLE_BASE = "https://www.google.com/"


def _is_google_host(host: str) -> bool:
    host = host.lower()
    return host == "google.com" or host.endswith(".google.com")


def goto_token(href: str | None, any_host: bool = False) -> str | None:
    """'/goto?url=<token>' (relative, or absolute on a Google host) -> '<token>'.
    any_host: also accept an absolute /goto URL on another host (the network
    listener matches the requests the resolver itself sent)."""
    if not href:
        return None
    parts = urlsplit(urljoin(GOOGLE_BASE, href))
    if parts.path != "/goto" or not (any_host or _is_google_host(parts.hostname or "")):
        return None
    return (parse_qs(parts.query).get("url") or [None])[0]


def goto_url(token: str, base: str = GOOGLE_BASE) -> str:
    """The URL to request to resolve `token`, on the host that served the page."""
    parts = urlsplit(base)
    origin = f"{parts.scheme}://{parts.netloc}/" if parts.scheme and parts.netloc else GOOGLE_BASE
    return f"{origin}goto?url={token}"


@dataclass
class LocationVerdict:
    url: str | None = None
    blocked: bool = False  # Google answered with its /sorry/ (unusual traffic) page


def destination_from_location(location: str | None, base: str = GOOGLE_BASE) -> LocationVerdict:
    """Validate the Location header of a /goto answer."""
    if not location:
        return LocationVerdict()
    absolute = urljoin(base, location)
    parts = urlsplit(absolute)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return LocationVerdict()
    # A relative Location stays on the Google host that answered the /goto.
    on_google = not urlsplit(location).netloc or _is_google_host(parts.hostname)
    if on_google and parts.path.startswith("/sorry/"):
        return LocationVerdict(blocked=True)
    if on_google and parts.path == "/url":
        return LocationVerdict(url=unwrap_google_redirect(absolute))
    return LocationVerdict(url=absolute)


@dataclass
class LinkMap:
    """Per-page link resolution shared by every parser.

    `resolved` is the token -> destination map from the fetcher. `wanted` records,
    in order, every /goto token a parser asked for - the fetcher runs the parsers
    once with an empty map to learn exactly which tokens to resolve.
    """

    resolved: Mapping[str, str] = field(default_factory=dict)
    wanted: list[str] = field(default_factory=list)

    def resolve(self, href: str | None) -> str | None:
        """The real destination of `href`, or None if it isn't known."""
        if not href or href.startswith(("#", "javascript:")):
            return None
        token = goto_token(href)
        if token is not None:
            if token not in self.wanted:
                self.wanted.append(token)
            return self.resolved.get(token)
        if href.startswith(("http://", "https://")):
            host = urlsplit(href).hostname or ""
            return unwrap_google_redirect(href) if _is_google_host(host) and urlsplit(href).path == "/url" else href
        if href.startswith("/url?"):
            return unwrap_google_redirect(href, base=GOOGLE_BASE)
        if href.startswith("/"):
            # A Google-internal link, e.g. "More results from www.reddit.com"
            # (/search?q=...+site:...). Its destination really is that Google URL.
            return urljoin(GOOGLE_BASE, href)
        return None

    def is_unresolved_goto(self, href: str | None) -> bool:
        token = goto_token(href)
        return token is not None and token not in self.resolved
