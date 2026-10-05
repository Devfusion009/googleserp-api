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
import json
import logging
import os
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Page

from .links import goto_token

# TEMPORARY diagnostic (remove after the redirect-sequence run): with
# DIAG_NAV_TRACE=1, log every Document request/response/redirect this page makes.
_NAV_TRACE = os.environ.get("DIAG_NAV_TRACE") == "1"
_navlog = logging.getLogger("serp.navtrace")

# document: the results page itself (and any redirect hop, e.g. to /sorry/)
# async: /async/ follow-ups - how the AI Overview (and other deferred blocks) load
# goto: /goto link resolutions, ours and any the page prefetches itself
# other_google: scripts, styles, logging pings... on Google hosts
# non_google: anything else
REQUEST_KINDS = ("document", "async", "goto", "other_google", "non_google")
GOOGLE_DOMAINS = ("google.com", "gstatic.com", "googleapis.com", "googleusercontent.com", "googleadservices.com", "doubleclick.net", "youtube.com", "ytimg.com")
# What Chromium reports for a request the resource blocker aborted (route.abort()).
BLOCKED_ERRORS = {"net::ERR_FAILED", "net::ERR_BLOCKED_BY_CLIENT"}


async def out_of_page_bytes(resp) -> int:
    """Bytes received for a response of Playwright's request client (APIResponse):
    status line + header block + body, as HTTP/1.1 puts them on the wire.

    Requests made with context.request (the /goto fallback, exit-IP checks) run
    outside the browser, so CDP never sees them, and Playwright has no size API
    for them (microsoft/playwright#5632). This reconstruction is exact for what
    it covers but misses the connection's CONNECT/TLS overhead, so a page that
    used such requests is marked bytes_in_partial and the benchmark's traffic
    guard adds OUT_OF_PAGE_ALLOWANCE_BYTES per request on top."""
    status_line = len(f"HTTP/1.1 {resp.status} {resp.status_text}\r\n".encode())
    headers = sum(len(h["name"].encode()) + len(h["value"].encode()) + 4 for h in resp.headers_array) + 2
    try:
        body = len(await resp.body())
    except Exception:  # body already disposed or unreadable - count the headers only
        body = 0
    return status_line + headers + body


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
        self.async_pending: set[str] = set()  # /async/ requests (the AIO loads this way) not finished yet
        self.async_done = 0  # /async/ requests finished or failed since the last reset() or results document
        self._main_frame: str | None = None

    async def attach(self, context: BrowserContext, page: Page) -> None:
        cdp = await context.new_cdp_session(page)
        tree = await cdp.send("Page.getFrameTree")
        self._main_frame = tree["frameTree"]["frame"]["id"]
        cdp.on("Network.requestWillBeSent", self._on_request)
        cdp.on("Network.responseReceivedExtraInfo", self._on_response_headers)
        cdp.on("Network.loadingFinished", self._on_finished)
        cdp.on("Network.loadingFailed", self._on_failed)
        if _NAV_TRACE:
            self._doc_ids: set[str] = set()
            cdp.on("Network.requestWillBeSent", self._trace_request)
            cdp.on("Network.responseReceived", self._trace_response)
            cdp.on("Network.responseReceivedExtraInfo", self._trace_response_headers)
            cdp.on("Network.loadingFailed", self._trace_failed)
            cdp.on("Network.requestWillBeSentExtraInfo", self._trace_request_headers)
        await cdp.send("Network.enable")

    def _trace_request_headers(self, ev: dict) -> None:
        # Headers as sent on the wire (cookies included). Can arrive before
        # requestWillBeSent, so filter on the header rather than _doc_ids.
        headers = {k.lower(): v for k, v in (ev.get("headers") or {}).items()}
        if headers.get("sec-fetch-dest") != "document":
            return
        cookies = [{"name": c.get("cookie", {}).get("name"), "value": c.get("cookie", {}).get("value"),
                    "domain": c.get("cookie", {}).get("domain"), "blocked": c.get("blockedReasons")}
                   for c in ev.get("associatedCookies") or []]
        _navlog.info("NAVTRACE request-headers rid=%s headers=%s cookies=%s", ev["requestId"],
                     json.dumps(ev.get("headers") or {}), json.dumps(cookies))

    def _trace_request(self, ev: dict) -> None:
        if ev.get("type") != "Document":
            return
        rid = ev["requestId"]
        self._doc_ids.add(rid)
        redir = ev.get("redirectResponse")
        if redir:
            loc = {k.lower(): v for k, v in (redir.get("headers") or {}).items()}.get("location")
            _navlog.info("NAVTRACE redirect rid=%s status=%s from=%s location=%s", rid, redir.get("status"), redir.get("url"), loc)
        init = ev.get("initiator") or {}
        _navlog.info("NAVTRACE request rid=%s frame=%s method=%s initiator=%s url=%s", rid, ev.get("frameId"),
                     ev.get("request", {}).get("method"), init.get("type"), ev.get("request", {}).get("url"))
        frames = ((init.get("stack") or {}).get("callFrames") or [])[:3]
        _navlog.info("NAVTRACE request-context rid=%s hasUserGesture=%s referrerPolicy=%s blink_headers=%s initiator_url=%s initiator_stack=%s",
                     rid, ev.get("hasUserGesture"), ev.get("request", {}).get("referrerPolicy"),
                     json.dumps(ev.get("request", {}).get("headers") or {}), init.get("url"),
                     json.dumps([{"fn": f.get("functionName"), "url": f.get("url"), "line": f.get("lineNumber")} for f in frames]))

    def _trace_response(self, ev: dict) -> None:
        if ev.get("type") != "Document":
            return
        r = ev.get("response") or {}
        _navlog.info("NAVTRACE response rid=%s status=%s url=%s", ev["requestId"], r.get("status"), r.get("url"))

    def _trace_response_headers(self, ev: dict) -> None:
        if ev["requestId"] not in self._doc_ids:
            return
        loc = {k.lower(): v for k, v in (ev.get("headers") or {}).items()}.get("location")
        _navlog.info("NAVTRACE response-headers rid=%s status=%s location=%s", ev["requestId"], ev.get("statusCode"), loc)
        _navlog.info("NAVTRACE response-headers-full rid=%s status=%s headers=%s", ev["requestId"], ev.get("statusCode"),
                     json.dumps(ev.get("headers") or {}))

    def _trace_failed(self, ev: dict) -> None:
        if ev["requestId"] in self._doc_ids:
            _navlog.info("NAVTRACE failed rid=%s error=%s canceled=%s", ev["requestId"], ev.get("errorText"), ev.get("canceled"))

    def reset(self) -> None:
        self.bytes = self.requests = 0
        self.kinds = dict.fromkeys(REQUEST_KINDS, 0)
        self._sent.clear()
        self._counted.clear()
        self._answered.clear()
        self._goto_urls.clear()
        self._redirects.clear()
        self.async_pending.clear()
        self.async_done = 0

    def _async_ended(self, request_id: str) -> None:
        if request_id in self.async_pending:
            self.async_pending.discard(request_id)
            self.async_done += 1

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
        if ev.get("type") == "Document" and ev.get("frameId") == self._main_frame:
            # A new page in the tab: /async/ requests of the page before it (the typed
            # search's homepage makes /async/hpba ones) say nothing about this page's AIO.
            self.async_pending.clear()
            self.async_done = 0
        if request_kind(url, ev.get("type")) == "async":
            self.async_pending.add(rid)
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
        self._async_ended(ev["requestId"])

    def _on_failed(self, ev: dict) -> None:
        if ev.get("errorText") not in BLOCKED_ERRORS or ev.get("canceled"):
            self._count(ev["requestId"])
        self._async_ended(ev["requestId"])
