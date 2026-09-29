"""Link resolution rules (app/links.py) and the /goto resolver with fakes."""
from types import SimpleNamespace

from playwright.async_api import Error as PlaywrightError

from app.config import Settings
from app.goto_resolver import resolve_goto
from app.links import LinkMap, destination_from_location, goto_token, goto_url

SERP = "https://www.google.com/search?q=x&gl=us&hl=en"


def test_goto_token_relative_and_absolute_google_only():
    assert goto_token("/goto?url=CAESabc") == "CAESabc"
    assert goto_token("https://www.google.com/goto?url=CAESabc") == "CAESabc"
    assert goto_token("https://example.com/goto?url=CAESabc") is None
    assert goto_token("https://example.com/goto?url=CAESabc", any_host=True) == "CAESabc"
    assert goto_token("/url?q=https://e.com") is None
    assert goto_token(None) is None


def test_goto_url_uses_the_pages_own_origin():
    assert goto_url("T1", SERP) == "https://www.google.com/goto?url=T1"
    assert goto_url("T1", "http://127.0.0.1:9/search?q=x") == "http://127.0.0.1:9/goto?url=T1"


def test_location_rules():
    assert destination_from_location("https://e.com/a?b=1#c").url == "https://e.com/a?b=1#c"
    assert destination_from_location("/url?q=https://e.com/x&sa=U").url == "https://e.com/x"
    assert destination_from_location("https://www.google.com/sorry/index?continue=x").blocked
    assert destination_from_location("/sorry/index?continue=x").blocked
    # relative = on whichever Google host answered, even when it isn't www.google.com
    assert destination_from_location("/sorry/index?continue=x", "https://www.google.co.uk/search?q=x").blocked
    assert not destination_from_location("https://example.com/sorry/page").blocked
    assert destination_from_location(None).url is None
    assert destination_from_location("javascript:alert(1)").url is None


def test_link_map_resolves_each_href_kind():
    links = LinkMap(resolved={"KNOWN": "https://dest.example/page"})
    assert links.resolve("https://e.com/a") == "https://e.com/a"
    assert links.resolve("/url?q=https://e.com/b&sa=U") == "https://e.com/b"
    assert links.resolve("/goto?url=KNOWN") == "https://dest.example/page"
    assert links.resolve("/goto?url=UNKNOWN") is None
    assert links.resolve("/search?q=x+site:reddit.com") == "https://www.google.com/search?q=x+site:reddit.com"
    assert links.resolve("#section") is None and links.resolve("") is None
    assert links.wanted == ["KNOWN", "UNKNOWN"]
    links.resolve("/goto?url=KNOWN")
    assert links.wanted == ["KNOWN", "UNKNOWN"]  # recorded once
    assert links.is_unresolved_goto("/goto?url=UNKNOWN") and not links.is_unresolved_goto("/goto?url=KNOWN")


# --- resolver, browser faked ---------------------------------------------------

class FakeResponse:
    def __init__(self, status, location=None):
        self.status = status
        self.status_text = "Found" if 300 <= status < 400 else "OK"
        self.headers = {"location": location} if location else {}
        self.headers_array = [{"name": "Location", "value": location}] if location else []

    async def body(self):
        return b""

    async def dispose(self):
        pass


class FakeRequest:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    async def get(self, url, **kw):
        self.calls.append((url, kw))
        answer = self.answers[url]
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakePage:
    def __init__(self, net=None, answers=None):
        self.url = SERP
        self.net = net
        self.evaluated = []
        self.context = SimpleNamespace(request=FakeRequest(answers or {}))

    async def evaluate(self, js, arg=None):
        self.evaluated.append(arg)
        if self.net is not None:
            self.net.on_fetch(arg["urls"])

    async def wait_for_timeout(self, ms):
        pass


class FakeNet:
    """Answers each in-page fetch the way CDP would report it."""

    def __init__(self, locations):
        self.locations, self.seen = locations, {}

    def on_fetch(self, urls):
        for u in urls:
            token = u.split("url=", 1)[1]
            if token in self.locations:
                self.seen[token] = self.locations[token]

    def goto_locations(self):
        return dict(self.seen)


S = Settings(_env_file=None, goto_concurrency=4, goto_timeout_ms=500)


async def test_in_page_resolution_needs_no_fallback():
    net = FakeNet({"A": "https://a.example/1", "B": "https://b.example/2"})
    page = FakePage(net)
    out = await resolve_goto(page, net, ["A", "B"], S)
    assert out.resolved == {"A": "https://a.example/1", "B": "https://b.example/2"}
    assert out.in_page == 2 and out.fallback == 0 and out.unresolved == []
    assert page.evaluated[0]["urls"] == ["https://www.google.com/goto?url=A", "https://www.google.com/goto?url=B"]
    assert page.context.request.calls == []


async def test_fallback_resolves_what_the_page_missed_without_following_redirects():
    net = FakeNet({"A": "https://a.example/1"})
    answers = {
        "https://www.google.com/goto?url=B": FakeResponse(302, "https://b.example/2"),
        "https://www.google.com/goto?url=C": FakeResponse(200),
        "https://www.google.com/goto?url=D": PlaywrightError("net::ERR_TIMED_OUT"),
    }
    page = FakePage(net, answers)
    out = await resolve_goto(page, net, ["A", "B", "C", "D"], S)
    assert out.resolved == {"A": "https://a.example/1", "B": "https://b.example/2"}
    assert out.unresolved == ["C", "D"] and out.fallback == 1
    assert all(kw["max_redirects"] == 0 for _, kw in page.context.request.calls)
    # B and C answered, D failed on the network: 3 requests left the page and
    # the two answers are counted byte for byte (status line + headers + body).
    assert out.fallback_requests == 3
    b = len("HTTP/1.1 302 Found\r\n") + len("Location") + len("https://b.example/2") + 4 + 2
    c = len("HTTP/1.1 200 OK\r\n") + 2
    assert out.fallback_bytes == b + c


async def test_without_a_network_listener_everything_goes_through_the_fallback():
    page = FakePage(None, {"https://www.google.com/goto?url=A": FakeResponse(302, "https://a.example/1")})
    out = await resolve_goto(page, None, ["A"], S)
    assert out.resolved == {"A": "https://a.example/1"} and out.in_page == 0 and page.evaluated == []


async def test_a_sorry_redirect_means_blocked_and_stops():
    net = FakeNet({"A": "https://www.google.com/sorry/index?continue=x"})
    page = FakePage(net, {"https://www.google.com/goto?url=B": FakeResponse(302, "https://b.example/2")})
    out = await resolve_goto(page, net, ["A", "B"], S)
    assert out.blocked and page.context.request.calls == []


def test_out_of_page_traffic_is_added_to_bytes_in_and_marked_partial():
    from app.fetcher import FetchResult, _add_out_of_page_traffic
    from app.goto_resolver import GotoResolution

    res = FetchResult(url_sent=SERP)
    res.timings = {"bytes_in": 100_000}
    res.usage = {"document": 1, "goto": 5, "goto_fallback": 2}
    res.goto = GotoResolution(fallback_requests=2, fallback_bytes=700)
    res.session = {"ip_checks": 2, "ip_check_bytes": 300}
    _add_out_of_page_traffic(res)
    assert res.timings["bytes_in"] == 101_000
    assert res.timings["out_of_page_requests"] == 4 and res.timings["bytes_out_of_page"] == 1000
    assert res.timings["bytes_in_partial"] is True
    assert res.requests_used == 1 + 5 + 2  # the fallback /goto requests are Google requests; IP checks aren't


def test_in_page_only_traffic_is_not_marked_partial():
    from app.fetcher import FetchResult, _add_out_of_page_traffic

    res = FetchResult(url_sent=SERP)
    res.timings = {"bytes_in": 100_000}
    res.usage = {"document": 1, "goto": 5}
    _add_out_of_page_traffic(res)
    assert res.timings == {"bytes_in": 100_000}
