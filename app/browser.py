"""Playwright lifecycle: one warm browser, a pool of CONCURRENCY page slots.

Each slot owns a browser context (proxy + locale are per context) and one page.

Proxy sessions and IP changes. A residential proxy's sticky session can end
early and hand out a new exit IP. Google's cookies belong to the IP they were
set on, so a browser context is tied to one proxy session and never carried
to another:
  - a literal `{session}` in the proxy URL is replaced with a fresh id each time
    a context is built, so every context is its own sticky session;
  - the context is rebuilt (new session) only between requests, never during
    one: when the proxy or locale changes, after a CAPTCHA, when it is older
    than PROXY_SESSION_MAX_SECONDS, or when the exit IP moved (see below);
  - with EXIT_IP_CHECK_URL set, the exit IP is read through the slot's proxy
    before and after each request. A change while idle -> fresh session before
    the request; a change during a request is recorded against that request
    (X-Proxy-Session, benchmark report) and the next request gets a fresh
    session. The request itself is judged on what Google returned - a page
    broken by the switch fails like any other, and is not retried.
"""
import asyncio
import ipaddress
import logging
import re
import secrets
import time
from pathlib import Path
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncContextManager, Protocol

from playwright.async_api import Browser, BrowserContext, Page, Playwright, Route, async_playwright

from .config import Settings
from .netwatch import NetworkWatch, out_of_page_bytes
from .proxy import ProxyProvider, make_provider, mask_proxy, to_playwright

# Init script from web-agent-master/google-search (src/search.ts), applied to every page.
REPO_FINGERPRINT_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => false });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'zh-CN'] });
window.chrome = { runtime: {}, loadTimes: function () {}, csi: function () {}, app: {} };
if (typeof WebGLRenderingContext !== 'undefined') {
  const getParameter = WebGLRenderingContext.prototype.getParameter;
  WebGLRenderingContext.prototype.getParameter = function (p) {
    if (p === 37445) return 'Intel Inc.';
    if (p === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.call(this, p);
  };
}
if (window === window.top) {
  Object.defineProperty(window.screen, 'width', { get: () => 1920 });
  Object.defineProperty(window.screen, 'height', { get: () => 1080 });
  Object.defineProperty(window.screen, 'colorDepth', { get: () => 24 });
  Object.defineProperty(window.screen, 'pixelDepth', { get: () => 24 });
}
"""

log = logging.getLogger("serp.browser")


class PageSlot(Protocol):
    """What Fetcher needs from a checked-out slot: a live Playwright Page, the
    proxy URL it's using (for logging) and the page's CDP network listener
    (traffic counts, /goto redirect Locations; None if unavailable)."""

    page: Page
    proxy: str | None
    net: NetworkWatch | None
    retire: str | None  # set to a reason to get a fresh context/session next time
    report: dict  # this request's proxy-session facts (session id, exit IPs)


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
    net: NetworkWatch | None = None
    uses: int = field(default=0)
    proxy_template: str | None = None  # proxy URL as configured, before {session}
    session: str | None = None
    created: float = 0.0
    exit_ip: str | None = None
    retire: str | None = None
    report: dict = field(default_factory=dict)
    ip_checked_at: float | None = None  # monotonic time of the last exit-IP check that answered


def locale_for(country: str | None, language: str | None) -> str:
    lang = (language or "en").split("-")[0].lower()
    cc = (country or "US").upper()
    return f"{lang}-{cc}"


IP_CANDIDATE_RE = re.compile(r"[0-9A-Fa-f:.]{2,45}")


def parse_ip(text: str) -> str | None:
    """First valid IPv4/IPv6 address in an IP-check answer (plain text or JSON)."""
    for candidate in IP_CANDIDATE_RE.findall(text or ""):
        try:
            return str(ipaddress.ip_address(candidate.strip(".")))
        except ValueError:
            continue
    return None


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
        if self.s.browser_executable_path:
            kwargs["executable_path"] = self.s.browser_executable_path
        if self.s.repo_fingerprint:
            kwargs["args"] = ["--disable-blink-features=AutomationControlled"]
        self.browser = await self._pw.chromium.launch(**kwargs)
        for i in range(max(1, self.s.concurrency)):
            self._slots.put_nowait(Slot(i))
        log.info("browser started channel=%s headless=%s slots=%d proxy_mode=%s",
                 self.s.browser_channel, self.s.headless, self.s.concurrency, self.s.proxy_mode)
        if self.s.prewarm_slots:
            await self.prewarm()

    async def prewarm(self) -> None:
        """Build every slot's context for the default locale now, so the first
        request doesn't wait for it. A slot that fails is built on first use."""
        slots = [self._slots.get_nowait() for _ in range(self._slots.qsize())]
        try:
            for slot in slots:
                try:
                    await self._prepare(slot, None, None)
                except Exception as e:
                    log.warning("slot=%d prewarm failed: %s", slot.index, str(e).splitlines()[0][:200])
                    await self._close(slot, "prewarm failed")
        finally:
            for slot in slots:
                self._slots.put_nowait(slot)

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

    async def exit_ip(self, slot: Slot) -> str | None:
        """The slot's current exit IP via EXIT_IP_CHECK_URL (through its proxy), or
        None when not configured or the check failed."""
        if not self.s.exit_ip_check_url or slot.context is None:
            return None
        # The check goes through the proxy outside the browser: count it and its
        # reconstructed bytes into this request's traffic (the fetcher adds them).
        slot.report["ip_checks"] = slot.report.get("ip_checks", 0) + 1
        try:
            resp = await slot.context.request.get(self.s.exit_ip_check_url, timeout=self.s.exit_ip_check_timeout_ms)
            ip = parse_ip(await resp.text()) if resp.ok else None
            if ip:
                slot.ip_checked_at = time.monotonic()
        except Exception as e:  # a failed check is "unknown", never a reason to fail the request
            log.warning("slot=%d exit IP check failed: %s", slot.index, str(e).splitlines()[0][:200])
            return None
        try:
            slot.report["ip_check_bytes"] = slot.report.get("ip_check_bytes", 0) + await out_of_page_bytes(resp)
            await resp.dispose()
        except Exception as e:  # accounting must not change the check's answer
            log.warning("slot=%d could not size the exit IP check: %s", slot.index, str(e).splitlines()[0][:200])
        return ip

    async def _close(self, slot: Slot, reason: str) -> None:
        log.info("slot=%d new proxy session: %s", slot.index, reason)
        if slot.context is not None:
            try:
                await slot.context.close()
            except Exception:
                pass
        slot.context = slot.page = slot.net = None

    async def _build(self, slot: Slot, template: str | None, locale: str) -> None:
        assert self.browser is not None
        slot.session = secrets.token_hex(4) if template and "{session}" in template else None
        proxy = template.replace("{session}", slot.session) if template and slot.session else template
        viewport = {"width": self.s.viewport_width, "height": self.s.viewport_height}
        opts = dict(
            viewport=viewport, locale=locale,
            extra_http_headers={"Accept-Language": f"{locale},{locale.split('-')[0]};q=0.9"},
        )
        if proxy:
            opts["proxy"] = to_playwright(proxy)
        state = self.s.repo_state_file
        if state and Path(state).exists():
            opts["storage_state"] = state
        slot.context = await self.browser.new_context(**opts)
        if self.s.repo_fingerprint:
            await slot.context.add_init_script(REPO_FINGERPRINT_JS)
        if self.s.block_resources:
            await slot.context.route("**/*", self._block)
        slot.page = await slot.context.new_page()
        slot.net = NetworkWatch()
        await slot.net.attach(slot.context, slot.page)
        slot.proxy_template, slot.proxy, slot.locale = template, proxy, locale
        slot.created, slot.retire = time.monotonic(), None
        slot.exit_ip = await self.exit_ip(slot)

    def _rebuild_reason(self, slot: Slot, template: str | None, locale: str) -> str | None:
        if slot.context is None:
            return None
        if template != slot.proxy_template or locale != slot.locale:
            return "proxy or locale changed"
        if slot.retire:
            return slot.retire
        max_age = self.s.proxy_session_max_seconds
        if max_age and time.monotonic() - slot.created >= max_age:
            return f"session older than PROXY_SESSION_MAX_SECONDS={max_age}"
        return None

    async def _prepare(self, slot: Slot, country: str | None, language: str | None) -> None:
        slot.report = {}  # this request's session facts; exit-IP checks count into it
        locale = locale_for(country, language)
        template = self.provider.next(country) if (self.provider.rotates or slot.context is None) else slot.proxy_template
        reason = self._rebuild_reason(slot, template, locale)
        if reason:
            await self._close(slot, reason)
        if slot.context is None:
            await self._build(slot, template, locale)
        elif self.s.exit_ip_check_url and not self._ip_checked_recently(slot):
            ip = await self.exit_ip(slot)
            if ip and slot.exit_ip and ip != slot.exit_ip:
                # The session moved to another IP while idle: don't bring this
                # IP's cookies to the new one.
                await self._close(slot, f"exit IP changed between requests ({slot.exit_ip} -> {ip})")
                await self._build(slot, template, locale)
            elif ip:
                slot.exit_ip = ip
        slot.report.update(session=slot.session, exit_ip=slot.exit_ip)
        log.info("slot=%d proxy=%s session=%s exit_ip=%s locale=%s",
                 slot.index, mask_proxy(slot.proxy), slot.session, slot.exit_ip, slot.locale)

    def _ip_checked_recently(self, slot: Slot) -> bool:
        recheck = self.s.exit_ip_recheck_seconds
        return bool(recheck and slot.ip_checked_at is not None and time.monotonic() - slot.ip_checked_at < recheck)

    @asynccontextmanager
    async def page(self, country: str | None = None, language: str | None = None):
        slot = await self._slots.get()
        try:
            await self._prepare(slot, country, language)
            slot.uses += 1
            yield slot
            if self.s.exit_ip_check_url:
                after = await self.exit_ip(slot)
                slot.report["exit_ip_after"] = after
                if after and slot.exit_ip and after != slot.exit_ip:
                    slot.report["ip_changed"] = True
                    slot.retire = f"exit IP changed during a request ({slot.exit_ip} -> {after})"
                    log.warning("slot=%d %s", slot.index, slot.retire)
                slot.exit_ip = after or slot.exit_ip
        except Exception:
            # a broken page/context is rebuilt next time
            if slot.context:
                try:
                    await slot.context.close()
                except Exception:
                    pass
            slot.context = slot.page = slot.net = None
            raise
        finally:
            self._slots.put_nowait(slot)
