"""Chrome DevTools Protocol listener for one page.

Two jobs:
  - traffic: bytes received over the network (headers + body as transferred,
    i.e. what comes through the proxy, before TLS overhead) and the number of
    requests since the last reset(). Blocked resources are never fetched, so
    they don't count.
  - /goto redirects: the status and Location of each /goto answer. Playwright
    hides the 302 of a fetch(..., {redirect: 'manual'}) once request routing is
    on (BLOCK_RESOURCES), but CDP still reports it (responseReceivedExtraInfo).
"""
from playwright.async_api import BrowserContext, Page

from .links import goto_token


class NetworkWatch:
    def __init__(self) -> None:
        self.bytes = 0
        self.requests = 0
        self._goto_urls: dict[str, str] = {}  # requestId -> /goto URL
        self._redirects: dict[str, str | None] = {}  # requestId -> Location of a 3xx answer

    async def attach(self, context: BrowserContext, page: Page) -> None:
        cdp = await context.new_cdp_session(page)
        cdp.on("Network.requestWillBeSent", self._on_request)
        cdp.on("Network.responseReceivedExtraInfo", self._on_response_headers)
        cdp.on("Network.loadingFinished", self._on_finished)
        await cdp.send("Network.enable")

    def reset(self) -> None:
        self.bytes = self.requests = 0
        self._goto_urls.clear()
        self._redirects.clear()

    def goto_locations(self) -> dict[str, str | None]:
        """/goto token -> Location header, for every /goto request answered with a redirect."""
        return {goto_token(url, any_host=True): self._redirects[rid] for rid, url in self._goto_urls.items() if rid in self._redirects}

    def _on_request(self, ev: dict) -> None:
        self.requests += 1
        url = ev.get("request", {}).get("url", "")
        if goto_token(url, any_host=True):
            self._goto_urls.setdefault(ev["requestId"], url)

    def _on_response_headers(self, ev: dict) -> None:
        # Arrives before or after requestWillBeSent, so it is kept per request id
        # and joined in goto_locations(). Only redirects are kept.
        if 300 <= (ev.get("statusCode") or 0) < 400:
            headers = {k.lower(): v for k, v in (ev.get("headers") or {}).items()}
            self._redirects.setdefault(ev["requestId"], headers.get("location"))

    def _on_finished(self, ev: dict) -> None:
        self.bytes += int(ev.get("encodedDataLength") or 0)
