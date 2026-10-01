"""Proxy sessions and exit-IP changes in BrowserManager, with a fake browser."""
import pytest

from app.browser import BrowserManager, Slot, parse_ip
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

    async def send(self, *a):
        return {}


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
