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

Timezone. A context's timezone can only be set when it is created, and the exit
IP (whose timezone it should match) is only known once the context exists. So
a new context is checked first; if the check names a timezone, that context is
closed unused and built again on the same proxy URL (same sticky session) with
it, before any page is opened.
"""
import asyncio
import ipaddress
import json
import logging
import os
import random
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncContextManager, Protocol
from zoneinfo import ZoneInfo

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from .config import Settings
from .consent import reject_consent
from .netwatch import NetworkWatch, out_of_page_bytes
from .proxy import ProxyProvider, make_provider, mask_proxy, to_playwright
from .proxy_forwarder import ProxyForwarder

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

# Chrome's own language setting (Settings.native_locale): for contexts in that locale the
# Accept-Language header ("en-US,en;q=0.9") and navigator.languages (["en-US"]) are produced
# by Chrome itself, as in a real Chrome set to that language, not by emulation and a
# hand-written header. Chrome reads --lang only on Windows; on Linux it takes the language
# from the locale environment (LANGUAGE / LANG), so both are set.
def native_args(s: Settings) -> list[str]:
    """Chrome's own language setting (Settings.native_locale), when native languages are on."""
    return [f"--lang={s.native_locale}"] if s.native_en_us_languages and s.native_locale else []


def launch_args(s: Settings) -> list[str]:
    """Chrome switches every launch gets (the app's and the POC runner's)."""
    args = native_args(s)
    if s.proxy_mode != "none" and s.webrtc_proxy_only:
        # WebRTC asks the OS for addresses and sends UDP past the proxy, which can reveal the
        # machine's own IP next to the proxy's; this keeps it to the proxy (Chrome's
        # WebRtcIPHandlingPolicy "disable_non_proxied_udp", as privacy extensions set it).
        args.append("--force-webrtc-ip-handling-policy=disable_non_proxied_udp")
    return args


def native_env(s: Settings) -> dict[str, str] | None:
    """Locale environment for the browser process (Linux reads the language from it)."""
    if not (s.native_en_us_languages and s.native_locale):
        return None
    lang, _, region = s.native_locale.partition("-")
    full = f"{lang}_{region}" if region else lang
    return {**os.environ, "LANGUAGE": f"{full}:{lang}", "LANG": f"{full}.UTF-8", "LC_ALL": f"{full}.UTF-8"}


class PageSlot(Protocol):
    """What Fetcher needs from a checked-out slot: a live Playwright Page, the
    proxy URL it's using (for logging) and the page's CDP network listener
    (traffic counts, /goto redirect Locations; None if unavailable)."""

    page: Page
    proxy: str | None
    net: NetworkWatch | None
    retire: str | None  # set to a reason to get a fresh context/session next time
    report: dict  # this request's proxy-session facts (session id, exit IPs)


# Chrome errors that mean the request never got past the proxy (live q41, 2026-10-10: the
# route to the proxy gateway dropped for ~1 s, "[Errno 101] Network is unreachable").
# Google saw nothing, so the session - its cookies and exit IP - is still good.
PROXY_UNREACHABLE_ERRORS = (
    "net::ERR_TUNNEL_CONNECTION_FAILED",
    "net::ERR_PROXY_CONNECTION_FAILED",
    "net::ERR_INTERNET_DISCONNECTED",
    "net::ERR_NETWORK_CHANGED",
)


def proxy_unreachable(text: str | None) -> bool:
    return any(e in (text or "") for e in PROXY_UNREACHABLE_ERRORS)


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
    exit_tz: str | None = None  # timezone named by the last exit-IP check
    served_results: bool = False  # Google has served this context a results page
    timezone: str | None = None  # the context's timezone (None: the host's)
    forwarder: ProxyForwarder | None = None  # local proxy holding the upstream login (PROXY_LOCAL_FORWARDER)


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


def valid_timezone(name) -> str | None:
    """`name` if it is an IANA timezone this machine knows (Chromium rejects others)."""
    if not isinstance(name, str) or not name or name.startswith(("/", ".")) or ".." in name:
        return None
    try:
        ZoneInfo(name)
    except Exception:
        return None
    return name


def parse_exit_check(text: str) -> tuple[str | None, str | None]:
    """(exit IP, timezone) from an IP-check answer: JSON such as ipinfo.io/json
    ({"ip", "timezone"}), ip-api.com ({"query", "timezone"}) or ipwho.is
    ({"ip", "timezone": {"id"}}), or plain text with just the IP."""
    try:
        data = json.loads(text or "")
    except ValueError:
        data = None
    if isinstance(data, dict):
        ip = next((parse_ip(str(data[k])) for k in ("ip", "query", "ip_address") if data.get(k)), None)
        tz = data.get("timezone")
        if isinstance(tz, dict):
            tz = tz.get("id") or tz.get("name")
        return ip or parse_ip(text), valid_timezone(tz)
    return parse_ip(text), None


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
        kwargs["args"] = kwargs.get("args", []) + launch_args(self.s)
        if native_env(self.s):
            kwargs["env"] = native_env(self.s)
        if self.s.proxy_mode != "none" and self.s.launch_proxy:
            kwargs["proxy"] = {"server": self.s.launch_proxy}  # see Settings.launch_proxy
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
            if slot.forwarder is not None:
                await slot.forwarder.close()
        if self.browser:
            await self.browser.close()
        if self._pw:
            await self._pw.stop()

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
            ip, tz = parse_exit_check(await resp.text()) if resp.ok else (None, None)
            if ip:
                slot.ip_checked_at, slot.exit_tz = time.monotonic(), tz
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
        if slot.forwarder is not None:
            await slot.forwarder.close()
            slot.forwarder = None

    async def _build(self, slot: Slot, template: str | None, locale: str) -> None:
        assert self.browser is not None
        slot.session = secrets.token_hex(4) if template and "{session}" in template else None
        proxy = template.replace("{session}", slot.session) if template and slot.session else template
        viewport = {"width": self.s.viewport_width, "height": self.s.viewport_height}
        opts = dict(viewport=viewport, screen={"width": self.s.screen_width, "height": self.s.screen_height})
        if not (self.s.native_en_us_languages and locale == self.s.native_locale):
            opts.update(locale=locale, extra_http_headers={"Accept-Language": f"{locale},{locale.split('-')[0]};q=0.9"})
        if slot.forwarder is not None:  # left over from a context that broke
            await slot.forwarder.close()
            slot.forwarder = None
        if proxy and self.s.proxy_local_forwarder and urlsplit(proxy).username and urlsplit(proxy).scheme in ("http", "https"):
            # Chrome gets a proxy without a login: with one, Playwright intercepts every request
            # and turns the HTTP cache off (see app/proxy_forwarder.py).
            slot.forwarder = ProxyForwarder(proxy)
            opts["proxy"] = {"server": await slot.forwarder.start()}
        elif proxy:
            opts["proxy"] = to_playwright(proxy)
        state = self.s.repo_state_file
        if state and Path(state).exists():
            opts["storage_state"] = state
        fixed_tz = valid_timezone(self.s.timezone_id)
        if self.s.timezone_id and not fixed_tz:
            log.warning("TIMEZONE_ID=%r is not a known IANA timezone; ignored", self.s.timezone_id)
        if fixed_tz:
            opts["timezone_id"] = fixed_tz
        slot.context = await self.browser.new_context(**opts)
        slot.exit_tz = None
        slot.exit_ip = await self.exit_ip(slot)
        tz = (slot.exit_tz if self.s.timezone_from_exit_ip else None) or fixed_tz
        if tz and tz != opts.get("timezone_id"):
            # Nothing has been opened in this context yet; build it again, same proxy
            # URL (same sticky session, so the same exit IP), with the exit's timezone.
            await slot.context.close()
            opts["timezone_id"] = tz
            slot.context = await self.browser.new_context(**opts)
        elif self.s.timezone_from_exit_ip and self.s.exit_ip_check_url and slot.exit_ip and not slot.exit_tz:
            log.warning("slot=%d exit-IP check named no timezone (EXIT_IP_CHECK_URL should return JSON with one, "
                        "e.g. https://ipinfo.io/json); timezone: %s", slot.index, fixed_tz or "the host's")
        slot.timezone = opts.get("timezone_id")
        slot.served_results = False
        if self.s.repo_fingerprint:
            await slot.context.add_init_script(REPO_FINGERPRINT_JS)
        slot.page = await slot.context.new_page()
        slot.net = NetworkWatch()
        blocked = [p.strip() for p in self.s.blocked_url_patterns.split(",") if p.strip()] if self.s.block_resources else []
        await slot.net.attach(slot.context, slot.page, blocked)
        slot.proxy_template, slot.proxy, slot.locale = template, proxy, locale
        slot.created, slot.retire = time.monotonic(), None
        await self._warm_up(slot)

    async def _warm_up(self, slot: Slot) -> None:
        """Open WARMUP_URLS in the new session before its first search (a cold session gets
        Google's results far less often than one that has browsed a few pages first). A page
        that fails is skipped; the traffic is logged, as it goes through the proxy."""
        urls = [u.strip() for u in self.s.warmup_urls.split(",") if u.strip()]
        if not urls or slot.page is None:
            return
        t0, start_bytes = time.monotonic(), slot.net.bytes if slot.net else 0
        opened = 0
        for url in urls:
            try:
                await slot.page.goto(url, wait_until="domcontentloaded", timeout=self.s.nav_timeout_ms)
                opened += 1
                # A visitor answers Google's consent dialog instead of browsing on with it open.
                await reject_consent(slot.page)
                lo, hi = sorted((self.s.warmup_dwell_min_ms, self.s.warmup_dwell_max_ms))
                await slot.page.wait_for_timeout(random.randint(lo, hi))
            except Exception as e:  # a warm-up page never fails the session
                log.warning("slot=%d warm-up page %s failed: %s", slot.index, url, str(e).splitlines()[0][:120])
        warm_bytes = (slot.net.bytes if slot.net else 0) - start_bytes
        log.info("slot=%d warmup done pages=%d/%d bytes=%d ms=%d", slot.index, opened, len(urls), warm_bytes, (time.monotonic() - t0) * 1000)

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
        locale = self.s.browser_locale or locale_for(country, language)
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
        slot.report.update(session=slot.session, exit_ip=slot.exit_ip, timezone=slot.timezone)
        log.info("slot=%d proxy=%s session=%s exit_ip=%s locale=%s timezone=%s",
                 slot.index, mask_proxy(slot.proxy), slot.session, slot.exit_ip, slot.locale, slot.timezone)

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
            if self.s.exit_ip_check_url and self.s.exit_ip_check_after:
                after = await self.exit_ip(slot)
                slot.report["exit_ip_after"] = after
                if after and slot.exit_ip and after != slot.exit_ip:
                    slot.report["ip_changed"] = True
                    slot.retire = f"exit IP changed during a request ({slot.exit_ip} -> {after})"
                    log.warning("slot=%d %s", slot.index, slot.retire)
                slot.exit_ip = after or slot.exit_ip
        except Exception as e:
            if slot.context is not None and proxy_unreachable(str(e)):
                # The proxy could not be reached: keep the session, but check its exit IP
                # again before the next request (a rebuilt context would mean a new warm-up
                # and a first search, the riskiest search for a CAPTCHA).
                slot.ip_checked_at = None
                log.warning("slot=%d proxy unreachable, session kept: %s", slot.index, str(e).splitlines()[0][:120])
                raise
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
