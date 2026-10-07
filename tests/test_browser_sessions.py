"""Proxy sessions and exit-IP changes in BrowserManager, with a fake browser."""
import pytest

from app.browser import BrowserManager, Slot, parse_exit_check, parse_ip
from app.config import Settings
from app.proxy import StaticProxy


class FakeResponse:
    def __init__(self, text, ok=True):
        self._text, self.ok = text, ok
        self.status, self.status_text = 200, "OK"
        self.headers_array = [{"name": "Content-Type", "value": "text/plain"}]

    async def text(self):
        return self._text

    async def body(self):
        return self._text.encode()

    async def dispose(self):
        pass


class FakeRequest:
    def __init__(self, browser):
        self.browser = browser

    async def get(self, url, **kw):
        return FakeResponse(self.browser.ips.pop(0) if self.browser.ips else "")


class FakeCDP:
    def on(self, *a):
        pass

    async def send(self, method, *a):
        return {"frameTree": {"frame": {"id": "MAIN"}}} if method == "Page.getFrameTree" else {}


class FakeContext:
    def __init__(self, browser, opts):
        self.opts, self.closed = opts, False
        self.request = FakeRequest(browser)

    async def route(self, *a):
        pass

    async def new_page(self):
        return object()

    async def new_cdp_session(self, page):
        return FakeCDP()

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, ips=()):
        self.contexts = []
        self.ips = list(ips)  # answers of the exit-IP check, in order

    async def new_context(self, **opts):
        self.contexts.append(FakeContext(self, opts))
        return self.contexts[-1]


PROXY = "http://user-session-{session}:pw@proxy.example:8000"


def manager(ips=(), **settings):
    s = Settings(_env_file=None, proxy_mode="static", proxy_url=PROXY, **settings)
    m = BrowserManager(s, StaticProxy(PROXY))
    m.browser = FakeBrowser(ips)
    m._slots.put_nowait(Slot(0))
    return m


def usernames(m):
    return [c.opts["proxy"]["username"] for c in m.browser.contexts]


async def use(m):
    async with m.page("US", "en") as slot:
        return slot


async def test_every_context_gets_its_own_sticky_session_id():
    m = manager()
    slot = await use(m)
    await use(m)
    assert len(m.browser.contexts) == 1  # same context, same session, reused
    slot.retire = "test"
    await use(m)
    names = usernames(m)
    assert len(names) == 2 and all(n.startswith("user-session-") and "{session}" not in n for n in names)
    assert names[0] != names[1]  # a new context never reuses the old session


async def test_session_is_rotated_between_requests_once_too_old():
    m = manager(proxy_session_max_seconds=60)
    slot = await use(m)
    await use(m)
    assert len(m.browser.contexts) == 1
    slot.created -= 61
    await use(m)
    assert len(m.browser.contexts) == 2 and m.browser.contexts[0].closed


async def test_ip_change_while_idle_gets_a_fresh_session_before_the_request():
    # request 1: built .1, after .1 | request 2: before .2 -> rebuilt (new session) .3, after .3
    # (recheck 0: check before every request, even right after the previous one)
    m = manager(ips=["203.0.113.1", "203.0.113.1", "203.0.113.2", "203.0.113.3", "203.0.113.3"],
                exit_ip_check_url="https://ip.example/", exit_ip_recheck_seconds=0)
    await use(m)
    slot = await use(m)
    assert len(m.browser.contexts) == 2 and m.browser.contexts[0].closed
    assert slot.report["exit_ip"] == "203.0.113.3" and not slot.report.get("ip_changed")


async def test_ip_change_during_a_request_is_recorded_and_the_session_retired():
    # build: .1 | request: after .9 | next request: rebuilt (new session) -> .4
    m = manager(ips=["203.0.113.1", "203.0.113.9", "203.0.113.4", "203.0.113.4"], exit_ip_check_url="https://ip.example/")
    slot = await use(m)
    report = slot.report
    assert report["exit_ip"] == "203.0.113.1" and report["exit_ip_after"] == "203.0.113.9" and report["ip_changed"]
    assert slot.retire and "during a request" in slot.retire
    await use(m)
    assert len(m.browser.contexts) == 2 and usernames(m)[0] != usernames(m)[1]
    assert report["ip_changed"]  # the earlier request's record is untouched
    # the checks went through the proxy too: counted, with their bytes, per request
    one = len("HTTP/1.1 200 OK\r\n") + len("Content-Type") + len("text/plain") + 4 + 2 + len("203.0.113.1")
    assert report["ip_checks"] == 2 and report["ip_check_bytes"] == 2 * one


async def test_a_failed_ip_check_is_unknown_not_a_change():
    m = manager(ips=["203.0.113.1", "", ""], exit_ip_check_url="https://ip.example/")
    slot = await use(m)
    assert not slot.report.get("ip_changed") and slot.retire is None


@pytest.mark.parametrize("text,ip", [
    ("203.0.113.7\n", "203.0.113.7"),
    ('{"ip": "2001:db8::42", "time": "10:58:40"}', "2001:db8::42"),
    ('{"time": "10:58:40", "ip": "198.51.100.3"}', "198.51.100.3"),
    ("no address here", None),
])
def test_parse_ip(text, ip):
    assert parse_ip(text) == ip


# --- timezone matched to the exit IP ---------------------------------------------

def test_exit_check_answers_give_ip_and_timezone():
    assert parse_exit_check('{"ip": "172.56.90.213", "city": "Dallas", "loc": "32.78,-96.80", "timezone": "America/Chicago"}') \
        == ("172.56.90.213", "America/Chicago")  # ipinfo.io/json
    assert parse_exit_check('{"timezone":"America/Los_Angeles","query":"172.56.127.192"}') == ("172.56.127.192", "America/Los_Angeles")  # ip-api
    assert parse_exit_check('{"ip": "203.0.113.5", "timezone": {"id": "Europe/Berlin"}}') == ("203.0.113.5", "Europe/Berlin")  # ipwho.is
    assert parse_exit_check("203.0.113.7\n") == ("203.0.113.7", None)  # ipify: no timezone
    assert parse_exit_check('{"ip": "203.0.113.7", "timezone": "Mars/Olympus"}') == ("203.0.113.7", None)  # unknown name
    assert parse_exit_check('{"ip": "203.0.113.7", "timezone": "../../etc/passwd"}') == ("203.0.113.7", None)


async def test_a_new_context_takes_the_exit_ips_timezone_on_the_same_session():
    m = manager(ips=['{"ip": "203.0.113.1", "timezone": "America/Chicago"}', "203.0.113.1"], exit_ip_check_url="https://ip.example/")
    slot = await use(m)
    probe, live = m.browser.contexts
    assert probe.closed and "timezone_id" not in probe.opts
    assert live.opts["timezone_id"] == "America/Chicago" and not live.closed
    assert probe.opts["proxy"] == live.opts["proxy"]  # same sticky session, so the same exit IP
    assert slot.report["timezone"] == "America/Chicago" and slot.report["exit_ip"] == "203.0.113.1"
    assert slot.report["ip_checks"] == 2  # the check while building + the one after the request


async def test_without_a_timezone_from_the_check_the_fixed_one_is_used_and_nothing_is_rebuilt():
    m = manager(ips=["203.0.113.1", "203.0.113.1"], exit_ip_check_url="https://ip.example/", timezone_id="America/New_York")
    slot = await use(m)
    assert len(m.browser.contexts) == 1 and m.browser.contexts[0].opts["timezone_id"] == "America/New_York"
    assert slot.report["timezone"] == "America/New_York"


async def test_timezone_matching_can_be_turned_off():
    m = manager(ips=['{"ip": "203.0.113.1", "timezone": "America/Chicago"}', "203.0.113.1"],
                exit_ip_check_url="https://ip.example/", timezone_from_exit_ip=False)
    await use(m)
    assert len(m.browser.contexts) == 1 and "timezone_id" not in m.browser.contexts[0].opts


async def test_an_unknown_fixed_timezone_is_ignored():
    m = manager(timezone_id="Not/AZone")
    await use(m)
    assert "timezone_id" not in m.browser.contexts[0].opts


# --- browser-wide proxy: Chrome's own background traffic never leaves directly ----

class FakeChromium:
    def __init__(self):
        self.kwargs = None

    async def launch(self, **kwargs):
        self.kwargs = kwargs
        return FakeBrowser()


class FakePlaywright:
    def __init__(self):
        self.chromium = FakeChromium()


async def _launch_kwargs(monkeypatch, **settings):
    import app.browser as b
    pw = FakePlaywright()

    class Starter:
        async def start(self):
            return pw

    monkeypatch.setattr(b, "async_playwright", lambda: Starter())
    s = Settings(_env_file=None, prewarm_slots=False, **settings)
    await BrowserManager(s, StaticProxy(PROXY)).start()
    return pw.chromium.kwargs


async def test_with_a_proxy_the_browser_wide_proxy_is_a_dead_end(monkeypatch):
    kw = await _launch_kwargs(monkeypatch, proxy_mode="static", proxy_url=PROXY)
    assert kw["proxy"] == {"server": "http://127.0.0.1:9"}


async def test_without_a_proxy_or_with_it_turned_off_there_is_no_browser_wide_proxy(monkeypatch):
    assert "proxy" not in await _launch_kwargs(monkeypatch)
    assert "proxy" not in await _launch_kwargs(monkeypatch, proxy_mode="static", proxy_url=PROXY, launch_proxy="")


# --- what the page reports: screen and languages ----------------------------------

async def test_the_screen_is_larger_than_the_viewport():
    m = manager()
    await use(m)
    opts = m.browser.contexts[0].opts
    assert opts["screen"] == {"width": 1920, "height": 1080}
    assert opts["viewport"]["width"] < 1920 and opts["viewport"]["height"] < 1080


async def test_en_us_languages_come_from_chrome_and_other_locales_are_emulated():
    m = manager()
    async with m.page("US", "en"):
        pass
    assert "locale" not in m.browser.contexts[0].opts and "extra_http_headers" not in m.browser.contexts[0].opts
    async with m.page("DE", "de"):
        pass
    de = m.browser.contexts[-1].opts
    assert de["locale"] == "de-DE" and de["extra_http_headers"]["Accept-Language"].startswith("de-DE")


async def test_a_fixed_browser_locale_overrides_the_requests_and_is_native_when_it_matches():
    m = manager(browser_locale="pl-PL", native_locale="pl-PL")
    await use(m)  # the request says US / en
    assert "locale" not in m.browser.contexts[0].opts  # Chrome itself is set to pl-PL


def test_the_native_locale_goes_to_chrome_as_flag_and_environment():
    from app.browser import native_args, native_env
    s = Settings(_env_file=None, native_locale="pl-PL")
    assert native_args(s) == ["--lang=pl-PL"]
    env = native_env(s)
    assert env["LANGUAGE"] == "pl_PL:pl" and env["LANG"] == "pl_PL.UTF-8" and env["LC_ALL"] == "pl_PL.UTF-8"
    assert native_env(Settings(_env_file=None, native_en_us_languages=False)) is None
