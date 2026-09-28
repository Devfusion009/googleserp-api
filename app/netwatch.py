"""Chrome DevTools Protocol listener for one page.

Three jobs:
  - traffic: bytes received over the network (headers + body as transferred,
    i.e. what comes through the proxy, before TLS overhead) since the last
    reset(). Blocked resources are never fetched, so they don't count.
  - request usage: every request that went out to the network, by kind
    (see REQUEST_KINDS). A request counts once it got a response or failed on
    the network; requests the resource blocker aborted never left the browser
    and don't count. Cached responses aren't network requests either.
  - /goto redirects: the status and Location of each /goto answer. Playwright
    hides the 302 of a fetch(..., {redirect: 'manual'}) once request routing is
    on (BLOCK_RESOURCES), but CDP still reports it (responseReceivedExtraInfo).
"""
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Page

from .links import goto_token

# document: the results page itself (and any redirect hop, e.g. to /sorry/)
# async: /async/ follow-ups - how the AI Overview (and other deferred blocks) load
# goto: /goto link resolutions, ours and any the page prefetches itself
# other_google: scripts, styles, logging pings... on Google hosts
# non_google: anything else
REQUEST_KINDS = ("document", "async", "goto", "other_google", "non_google")
GOOGLE_DOMAINS = ("google.com", "gstatic.com", "googleapis.com", "googleusercontent.com", "googleadservices.com", "doubleclick.net", "youtube.com", "ytimg.com")
# What Chromium reports for a request the resource blocker aborted (route.abort()).
BLOCKED_ERRORS = {"net::ERR_FAILED", "net::ERR_BLOCKED_BY_CLIENT"}


def _is_google_owned(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in GOOGLE_DOMAINS)


def request_kind(url: str, resource_type: str | None) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if goto_token(url, any_host=True):
        return "goto"
    if host == "google.com" or host.endswith(".google.com"):
        if resource_type == "Document":
            return "document"
        if parts.path.startswith("/async/"):
            return "async"
    return "other_google" if _is_google_owned(host) else "non_google"


class NetworkWatch:
    def __init__(self) -> None:
        self.bytes = 0
        self.requests = 0
        self.kinds: dict[str, int] = dict.fromkeys(REQUEST_KINDS, 0)
        self._sent: dict[str, tuple[str, str | None]] = {}  # requestId -> (url, type), current hop
        self._counted: set[tuple[str, str]] = set()  # (requestId, url) hops already counted
        self._answered: set[str] = set()  # requestIds whose current hop got response headers
        self._goto_urls: dict[str, str] = {}  # requestId -> /goto URL
        self._redirects: dict[str, str | None] = {}  # requestId -> Location of a 3xx answer

    async def attach(self, context: BrowserContext, page: Page) -> None:
        cdp = await context.new_cdp_session(page)
        cdp.on("Network.requestWillBeSent", self._on_request)
        cdp.on("Network.responseReceivedExtraInfo", self._on_response_headers)
        cdp.on("Network.loadingFinished", self._on_finished)
        cdp.on("Network.loadingFailed", self._on_failed)
        await cdp.send("Network.enable")

    def reset(self) -> None:
        self.bytes = self.requests = 0
        self.kinds = dict.fromkeys(REQUEST_KINDS, 0)
        self._sent.clear()
        self._counted.clear()
        self._answered.clear()
        self._goto_urls.clear()
        self._redirects.clear()

    def goto_locations(self) -> dict[str, str | None]:
        """/goto token -> Location header, for every /goto request answered with a redirect."""
        return {goto_token(url, any_host=True): self._redirects[rid] for rid, url in self._goto_urls.items() if rid in self._redirects}

    def _count(self, request_id: str) -> None:
        url, rtype = self._sent.get(request_id, ("", None))
        if not url or (request_id, url) in self._counted:
            return
        self._counted.add((request_id, url))
        self.requests += 1
        self.kinds[request_kind(url, rtype)] += 1

    def _on_request(self, ev: dict) -> None:
        rid = ev["requestId"]
        if ev.get("redirectResponse"):
            self._count(rid)  # the hop that was answered with this redirect
            self._answered.discard(rid)
        url = ev.get("request", {}).get("url", "")
        self._sent[rid] = (url, ev.get("type"))
        if goto_token(url, any_host=True):
            self._goto_urls.setdefault(rid, url)
        if rid in self._answered:  # its response headers arrived first
            self._count(rid)

    def _on_response_headers(self, ev: dict) -> None:
        # Counted here, as soon as the answer arrives - loadingFinished can come
        # after the counters are read. Arrives before or after requestWillBeSent,
        # so it is kept per request id. Redirect Locations are joined in
        # goto_locations().
        rid = ev["requestId"]
        self._answered.add(rid)
        self._count(rid)
        if 300 <= (ev.get("statusCode") or 0) < 400:
            headers = {k.lower(): v for k, v in (ev.get("headers") or {}).items()}
            self._redirects.setdefault(rid, headers.get("location"))

    def _on_finished(self, ev: dict) -> None:
        self.bytes += int(ev.get("encodedDataLength") or 0)
        self._count(ev["requestId"])

    def _on_failed(self, ev: dict) -> None:
        if ev.get("errorText") not in BLOCKED_ERRORS or ev.get("canceled"):
            self._count(ev["requestId"])
