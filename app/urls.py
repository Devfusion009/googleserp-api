"""URL helpers: validation, Google redirect unwrapping, text-fragment stripping, paging.

Rule: the client's URL is never re-encoded. We only inspect it with urlsplit and,
for extra pages, append "&start=N" to the raw string.
"""
from urllib.parse import parse_qs, urljoin, urlsplit

ALLOWED_HOSTS = {"google.com", "www.google.com"}


class InvalidUrl(ValueError):
    pass


def validate_search_url(url: str) -> str:
    """Return the URL unchanged if it is a Google search URL, else raise InvalidUrl."""
    if not isinstance(url, str) or not url.strip():
        raise InvalidUrl("url is empty")
    if url != url.strip() or any(c in url for c in "\r\n\t "):
        raise InvalidUrl("url contains whitespace")
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http"):
        raise InvalidUrl("url must use https or http")
    if parts.username or parts.password or parts.port:
        raise InvalidUrl("url must not contain credentials or a port")
    host = (parts.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise InvalidUrl(f"host '{host}' is not google.com or www.google.com")
    if parts.path != "/search":
        raise InvalidUrl(f"path '{parts.path}' is not /search")
    if not parse_qs(parts.query).get("q"):
        raise InvalidUrl("url has no q= parameter")
    return url


def page_url(url: str, page_index: int) -> str:
    """Page 1 (index 0) is the client URL untouched; later pages append &start=10*i."""
    if page_index == 0:
        return url
    base, sep, frag = url.partition("#")
    joiner = "&" if urlsplit(base).query else "?"
    return f"{base}{joiner}start={10 * page_index}" + (sep + frag if sep else "")


def unwrap_google_redirect(href: str | None, base: str = "https://www.google.com/") -> str | None:
    """Turn '/url?q=https://x&sa=...' into 'https://x'. Other links are made absolute."""
    if not href:
        return None
    absolute = urljoin(base, href)
    parts = urlsplit(absolute)
    if (parts.hostname or "").endswith("google.com") and parts.path == "/url":
        qs = parse_qs(parts.query)
        target = (qs.get("q") or qs.get("url") or [None])[0]
        return target
    return absolute


def strip_text_fragment(url: str | None) -> str | None:
    """Remove '#:~:text=...' (and a trailing ':~:' directive after a normal fragment)."""
    if not url:
        return url
    base, sep, frag = url.partition("#")
    if not sep:
        return url
    keep = frag.split(":~:", 1)[0]
    return f"{base}#{keep}" if keep else base


def is_google_url(url: str | None) -> bool:
    if not url:
        return False
    host = (urlsplit(url).hostname or "").lower()
    return host == "google.com" or host.endswith(".google.com") or host.startswith("google.")
