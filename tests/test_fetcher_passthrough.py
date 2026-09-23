"""The client's URL must reach the browser byte-for-byte (page mocked)."""
from contextlib import asynccontextmanager
from types import SimpleNamespace

from app.config import Settings
from app.fetcher import Fetcher

DIFFICULT = "https://www.google.com/search?q=flights%20to%20brussels%20from%20shanghai&gl=us&hl=us"
HTML = '<html><body><div id="search"><div id="rso"><div><a href="https://e.com"><h3>E</h3></a></div></div></div></body></html>'


class FakePage:
    def __init__(self):
        self.goto_calls = []
        self.url = "about:blank"

    async def goto(self, url, **kw):
        self.goto_calls.append(url)
        self.url = url

    async def content(self):
        return HTML

    async def wait_for_selector(self, *a, **kw):
        return True

    async def evaluate(self, *a, **kw):
        return {"present": False}

    async def wait_for_timeout(self, ms):
        return None


class FakeBrowsers:
    def __init__(self):
        self.page_obj = FakePage()
        self.calls = []

    @asynccontextmanager
    async def page(self, country=None, language=None):
        self.calls.append((country, language))
        yield SimpleNamespace(page=self.page_obj, proxy=None)


async def test_difficult_url_reaches_browser_unchanged():
    s = Settings(_env_file=None, debug_artifacts=False, aio_appear_wait_ms=0)
    fb = FakeBrowsers()
    r = await Fetcher(s, fb).fetch(DIFFICULT, "US", "en")
    assert fb.page_obj.goto_calls == [DIFFICULT]
    assert fb.page_obj.goto_calls[0].encode() == DIFFICULT.encode()
    assert "hl=us" in fb.page_obj.goto_calls[0]
    assert r.url_sent == DIFFICULT
    assert r.classification.value == "ok"
    assert fb.calls == [("US", "en")]
