"""Playwright lifecycle: one warm browser, a pool of CONCURRENCY page slots.

Each slot owns a browser context (proxy + locale are per context) and one page.
The context is rebuilt only when the proxy or locale must change.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncContextManager, Protocol

from playwright.async_api import Browser, BrowserContext, Page, Playwright, Route, async_playwright

from .config import Settings
from .proxy import ProxyProvider, make_provider, mask_proxy, to_playwright

log = logging.getLogger("serp.browser")


class PageSlot(Protocol):
    """What Fetcher needs from a checked-out slot: a live Playwright Page and
    the proxy URL it's using (for logging)."""

    page: Page
    proxy: str | None


class PagePool(Protocol):
    """What Fetcher needs from its browser pool - checking a slot in and out.
    BrowserManager satisfies this structurally; so does a test double (see
    tests/test_fetcher_passthrough.py)."""

    def page(self, country: str | None = None, language: str | None = None) -> AsyncContextManager[PageSlot]: ...


@dataclass
class Slot:
    index: int
    context: BrowserContext | None = None
    page: Page | None = None
    proxy: str | None = None
    locale: str | None = None
    uses: int = field(default=0)


def locale_for(country: str | None, language: str | None) -> str:
    lang = (language or "en").split("-")[0].lower()
    cc = (country or "US").upper()
    return f"{lang}-{cc}"


class BrowserManager:
    def __init__(self, settings: Settings, provider: ProxyProvider | None = None):
        self.s = settings
        self.provider = provider or make_provider(settings)
        self._pw: Playwright | None = None
        self.browser: Browser | None = None
        self._slots: asyncio.Queue[Slot] = asyncio.Queue()

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        kwargs = {"headless": self.s.headless}
        if self.s.browser_channel == "chrome":
            kwargs["channel"] = "chrome"
        self.browser = await self._pw.chromium.launch(**kwargs)
        for i in range(max(1, self.s.concurrency)):
            self._slots.put_nowait(Slot(i))
        log.info("browser started channel=%s headless=%s slots=%d proxy_mode=%s",
                 self.s.browser_channel, self.s.headless, self.s.concurrency, self.s.proxy_mode)

    async def stop(self) -> None:
        while not self._slots.empty():
            slot = self._slots.get_nowait()
            if slot.context:
                await slot.context.close()
        if self.browser:
            await self.browser.close()
        if self._pw:
            await self._pw.stop()

    async def _block(self, route: Route) -> None:
        blocked = set(self.s.blocked_resource_types.split(","))
        if route.request.resource_type in blocked:
            await route.abort()
        else:
            await route.continue_()

    async def _prepare(self, slot: Slot, country: str | None, language: str | None) -> None:
        locale = locale_for(country, language)
        proxy = self.provider.next(country) if (self.provider.rotates or slot.context is None) else slot.proxy
        if slot.context is not None and (proxy != slot.proxy or locale != slot.locale):
            await slot.context.close()
            slot.context = slot.page = None
        if slot.context is None:
            assert self.browser is not None
            viewport = {"width": self.s.viewport_width, "height": self.s.viewport_height}
            opts = dict(
                viewport=viewport, locale=locale,
                extra_http_headers={"Accept-Language": f"{locale},{locale.split('-')[0]};q=0.9"},
            )
            if proxy:
                opts["proxy"] = to_playwright(proxy)
            slot.context = await self.browser.new_context(**opts)
            if self.s.block_resources:
                await slot.context.route("**/*", self._block)
            slot.page = await slot.context.new_page()
            slot.proxy, slot.locale = proxy, locale
        log.info("slot=%d proxy=%s locale=%s", slot.index, mask_proxy(slot.proxy), slot.locale)

    @asynccontextmanager
    async def page(self, country: str | None = None, language: str | None = None):
        slot = await self._slots.get()
        try:
            await self._prepare(slot, country, language)
            slot.uses += 1
            yield slot
        except Exception:
            # a broken page/context is rebuilt next time
            if slot.context:
                try:
                    await slot.context.close()
                except Exception:
                    pass
            slot.context = slot.page = None
            raise
        finally:
            self._slots.put_nowait(slot)
