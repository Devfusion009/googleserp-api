"""Fetcher._wait_aio: expanding the AI Overview ("Show more" / "Show all").

The page is faked: the probe reports the AI Overview's text length and its
expand buttons, and each click either fails, does nothing, or expands. A button
only counts as expanded when the page shows it (the button hides or changes
label, aria-expanded turns true, or the text grows); anything else is retried
within AIO_MAX_WAIT_MS and then reported as incomplete.
"""
import asyncio
import re

from playwright.async_api import Error as PlaywrightError

from app.config import Settings
from app.fetcher import AIO_PROBE_JS, Fetcher


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.id = re.search(r'data-serp-btn="([^"]+)"', selector).group(1)

    @property
    def first(self):
        return self

    async def click(self, timeout=None):
        self.page.clicks.append(self.id)
        button = self.page.buttons[self.id]
        behaviour = button["on_click"].pop(0) if button["on_click"] else "nothing"
        if behaviour == "raise":
            raise PlaywrightError("locator.click: Element is not visible")
        if behaviour == "hide":
            button["visible"] = False
            self.page.len += 500
        elif behaviour == "relabel":
            button["label"] = "Show less"
        elif behaviour == "grow":
            self.page.len += 500


class FakePage:
    url = "https://www.google.com/search?q=x"

    def __init__(self, buttons):
        self.len = 1200
        self.clicks = []
        self.buttons = {str(i): {"label": label, "visible": True, "expanded": None, "on_click": list(behaviours)}
                        for i, (label, behaviours) in enumerate(buttons, 1)}

    async def evaluate(self, js, *args):
        assert js == AIO_PROBE_JS
        return {
            "present": True, "len": self.len, "busy": False,
            "buttons": [{"id": i, "label": b["label"], "visible": b["visible"], "expanded": b["expanded"]}
                        for i, b in self.buttons.items()],
        }

    def locator(self, selector):
        return FakeLocator(self, selector)

    async def wait_for_timeout(self, ms):
        await asyncio.sleep(ms / 1000)


def fetcher(max_wait_ms=2500):
    return Fetcher(Settings(_env_file=None, aio_appear_wait_ms=0, aio_max_wait_ms=max_wait_ms), browsers=None)


async def test_a_click_that_raises_is_not_reported_complete():
    # The reviewer's case: every click on "Show more" fails.
    page = FakePage([("Show more", ["raise", "raise", "raise", "raise"])])
    ok, reason = await fetcher()._wait_aio(page)
    assert not ok
    assert "Show more" in reason and "not visible" in reason
    assert 1 < len(page.clicks) <= 3  # retried, within the attempt limit


async def test_a_failed_click_is_retried_and_counts_once_it_works():
    page = FakePage([("Show more", ["raise", "hide"])])
    ok, reason = await fetcher()._wait_aio(page)
    assert ok, reason
    assert page.clicks == ["1", "1"]


async def test_a_click_with_no_visible_effect_is_not_expansion():
    page = FakePage([("Show all", ["nothing", "nothing", "nothing"])])
    ok, reason = await fetcher()._wait_aio(page)
    assert not ok and "Show all" in reason and "no visible change" in reason


async def test_expansion_is_verified_by_label_change_or_growth():
    page = FakePage([("Show more", ["relabel"]), ("Show all", ["grow"])])
    ok, reason = await fetcher()._wait_aio(page)
    assert ok, reason
    assert page.clicks == ["1", "2"]  # each clicked once; the grown "Show all" is not clicked again


async def test_running_out_of_time_with_a_button_left_is_incomplete():
    page = FakePage([("Show more", ["raise"] * 20)])
    ok, reason = await fetcher(max_wait_ms=700)._wait_aio(page)
    assert not ok and "Show more" in reason


async def test_no_buttons_is_complete():
    ok, reason = await fetcher()._wait_aio(FakePage([]))
    assert ok and reason == "AI Overview complete"
