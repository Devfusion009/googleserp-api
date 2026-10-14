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
from app.fetcher import AIO_PROBE_JS, MARK_HIDDEN_JS, UNMARK_HIDDEN_JS, Fetcher


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


COMPLETE_HTML = ('<html><body><div><h2>AI Overview</h2><div class="n6owBd">' + "An answer. " * 30
                 + "</div></div></body></html>")
PLACEHOLDER_HTML = "<html><body><div><h2>AI Overview</h2><div>AI Mode reply for x</div></div></body></html>"


class FakePage:
    url = "https://www.google.com/search?q=x"

    def __init__(self, buttons):
        self.html = COMPLETE_HTML  # what page.content() returns: the classifier's view of the page
        self.len = 1200
        self.answer = True  # the block holds answer text (paragraph, section heading or bullet)
        self.clicks = []
        self.buttons = {str(i): {"label": label, "visible": True, "expanded": None, "on_click": list(behaviours)}
                        for i, (label, behaviours) in enumerate(buttons, 1)}

    async def content(self):
        return self.html

    async def evaluate(self, js, *args):
        if js != AIO_PROBE_JS:
            assert js in (MARK_HIDDEN_JS, UNMARK_HIDDEN_JS)
            return 0
        return {
            "present": True, "len": self.len, "busy": False, "answer": self.answer,
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


# --- deferred AI Overview: the block arrives as a shell, filled by an /async/ request ---

class FakeNet:
    """The two NetworkWatch fields _wait_aio reads."""

    def __init__(self, pending=(), done=0):
        self.async_pending, self.async_done = set(pending), done


async def test_a_shell_is_not_settled_while_its_async_request_is_in_flight():
    page, net = FakePage([]), FakeNet(pending={"r1"})
    page.len = 40  # heading + "AI Mode reply for ..."

    async def answer_arrives():
        await asyncio.sleep(0.8)
        page.len = 1200
        net.async_pending.clear()
        net.async_done = 1

    task = asyncio.create_task(answer_arrives())
    ok, reason = await fetcher()._wait_aio(page, net)
    await task
    assert ok, reason
    assert page.len == 1200  # it waited for the answer instead of settling on the shell


async def test_a_shell_waits_for_an_async_request_to_start_and_finish():
    # No /async/ request seen yet: a short, stable block is not taken as settled.
    page, net = FakePage([]), FakeNet()
    page.len = 40
    ok, reason = await fetcher(max_wait_ms=700)._wait_aio(page, net)
    assert not ok and "not finished" in reason


async def test_a_short_answer_after_its_async_request_finished_is_left_to_the_classifier():
    # A short block with some answer text settles once the request came back; the
    # classifier judges whether the text is enough.
    page, net = FakePage([]), FakeNet(done=1)
    page.len = 40
    ok, reason = await fetcher()._wait_aio(page, net)
    assert ok and reason == "AI Overview complete"


# --- the placeholder shell ("AI Mode reply for ..." over a "Searching" skeleton) ---

async def test_a_placeholder_shell_is_not_settled_even_when_the_network_looks_done():
    # smoke-de q04/q45: an /async/ request had finished (on the typed search's homepage)
    # and the shell was declared complete after ~550 ms. Now it waits to the deadline.
    page, net = FakePage([]), FakeNet(done=1)
    page.len, page.answer = 40, False
    ok, reason = await fetcher(max_wait_ms=700)._wait_aio(page, net)
    assert not ok and "still loading after 700 ms" in reason and "placeholder" in reason


async def test_a_placeholder_shell_without_a_network_watcher_is_not_settled():
    page = FakePage([])
    page.len, page.answer = 40, False
    ok, reason = await fetcher(max_wait_ms=700)._wait_aio(page)
    assert not ok and "still loading" in reason


async def test_a_placeholder_shell_that_fills_in_late_is_complete():
    page, net = FakePage([]), FakeNet(done=1)
    page.len, page.answer = 40, False

    async def answer_arrives():
        await asyncio.sleep(1.0)
        page.len, page.answer = 1200, True

    task = asyncio.create_task(answer_arrives())
    ok, reason = await fetcher()._wait_aio(page, net)
    await task
    assert ok and reason == "AI Overview complete"
    assert page.len == 1200


# --- the probe says done, the HTML the classifier reads says placeholder (live q18) ---

async def test_the_wait_does_not_end_while_the_classifier_still_sees_the_placeholder():
    # Poland q18 (2026-10-10): the probe took the block as answered after 554 ms, the
    # captured HTML held only "AI Mode reply for ...", the answer streamed in after.
    page, net = FakePage([]), FakeNet(done=1)
    page.html = PLACEHOLDER_HTML

    async def answer_arrives():
        await asyncio.sleep(1.0)
        page.html = COMPLETE_HTML

    task = asyncio.create_task(answer_arrives())
    ok, reason = await fetcher()._wait_aio(page, net)
    seen_when_done = page.html
    await task
    assert ok and reason == "AI Overview complete"
    assert seen_when_done == COMPLETE_HTML  # it waited for the answer


async def test_a_placeholder_the_classifier_sees_until_the_deadline_is_incomplete():
    page, net = FakePage([]), FakeNet(done=1)
    page.html = PLACEHOLDER_HTML
    ok, reason = await fetcher(max_wait_ms=900)._wait_aio(page, net)
    assert not ok and "still loading after 900 ms" in reason and "placeholder" in reason


async def test_an_unreadable_page_falls_back_to_the_probe():
    page = FakePage([])

    async def content():
        raise PlaywrightError("Target page, context or browser has been closed")
    page.content = content
    ok, reason = await fetcher()._wait_aio(page)
    assert ok and reason == "AI Overview complete"


# --- controls whose code Google lazy-loads (mobile run 2026-10-05, "how does dns work") ---

class ScriptNet(FakeNet):
    """FakeNet plus the script tracking _wait_aio reads."""

    def __init__(self):
        super().__init__(done=1)
        self.scripts_pending: set[str] = set()
        self.loaded_at = 0.0

    def scripts_quiet(self, idle_s):
        import time
        return not self.scripts_pending and time.monotonic() - self.loaded_at >= idle_s


async def test_a_click_while_scripts_load_is_awaited_not_repeated():
    # Clicked while the control's code is loading: the effect shows once the scripts are
    # in. One click, no "no visible change" retry that could toggle it back.
    page, net = FakePage([("Show all", ["nothing"] * 3)]), ScriptNet()
    net.scripts_pending = {"s1"}

    async def scripts_arrive():
        import time
        await asyncio.sleep(2.5)  # well past EXPAND_VERIFY_MS
        net.scripts_pending.clear(); net.loaded_at = time.monotonic()
        page.buttons["1"]["visible"] = False  # the queued click takes effect
        page.len += 500

    task = asyncio.create_task(scripts_arrive())
    ok, reason = await fetcher(max_wait_ms=6000)._wait_aio(page, net)
    await task
    assert ok, reason
    assert page.clicks == ["1"]


async def test_a_control_revealed_by_an_expansion_waits_for_scripts_to_go_quiet():
    # The overview's own 'Show more' is clicked right away; the 'Show all' that follows it
    # waits for the code Google loads after the first expansion.
    page, net = FakePage([("Show more", ["hide"]), ("Show all", ["hide"])]), ScriptNet()
    net.scripts_pending = {"s1"}
    clicked_while_loading = []
    real_locator = page.locator

    def locator(selector):
        clicked_while_loading.append(bool(net.scripts_pending))
        return real_locator(selector)

    page.locator = locator

    async def scripts_arrive():
        import time
        await asyncio.sleep(0.8)
        net.scripts_pending.clear(); net.loaded_at = time.monotonic()

    task = asyncio.create_task(scripts_arrive())
    ok, reason = await fetcher(max_wait_ms=6000)._wait_aio(page, net)
    await task
    assert ok, reason
    assert clicked_while_loading == [True, False]


async def test_scripts_that_never_go_quiet_do_not_block_the_click():
    page, net = FakePage([("Show more", ["hide"])]), ScriptNet()
    net.scripts_pending = {"forever"}
    ok, reason = await fetcher(max_wait_ms=6000)._wait_aio(page, net)
    assert ok, reason
    assert page.clicks == ["1"]


async def test_a_show_all_whose_cards_are_already_in_the_page_is_not_clicked():
    # Live: the sources' 'Show all' could not be confirmed in time, but every card it reveals
    # was already in the page (hidden). Such a 'Show all' is not pending.
    page = FakePage([("Show more", ["hide"]), ("Show all", ["nothing"] * 3)])
    real_evaluate = page.evaluate

    async def evaluate(js, *args):
        probe = await real_evaluate(js, *args)
        for b in probe["buttons"] if isinstance(probe, dict) else ():
            b["hiddenCards"] = 6 if b["label"] == "Show all" else 0
        return probe

    page.evaluate = evaluate
    ok, reason = await fetcher()._wait_aio(page)
    assert ok and reason == "AI Overview complete"
    assert page.clicks == ["1"]  # only 'Show more'


async def test_a_show_all_without_hidden_cards_in_the_page_is_still_clicked():
    page = FakePage([("Show all", ["hide"])])
    ok, reason = await fetcher()._wait_aio(page)
    assert ok and page.clicks == ["1"]


async def test_page_html_is_read_again_while_the_page_is_navigating():
    from app.fetcher import _page_html

    class Navigating:
        def __init__(self):
            self.calls = 0

        async def content(self):
            self.calls += 1
            if self.calls == 1:
                raise PlaywrightError("Page.content: Unable to retrieve content because the page is navigating and changing the content.")
            return "<html>ok</html>"

        async def wait_for_load_state(self, state):
            pass

    page = Navigating()
    assert await _page_html(page) == "<html>ok</html>" and page.calls == 2
