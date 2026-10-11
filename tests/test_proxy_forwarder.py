"""The local forwarder adds the upstream proxy's login, and with it Chrome keeps its HTTP
cache (with the login given to Playwright, every request is intercepted and the cache is off)."""
import asyncio
import base64
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from app.proxy_forwarder import ProxyForwarder

AUTH = "Basic " + base64.b64encode(b"user-session-ab12:p@ss").decode()


class UpstreamProxy:
    """A proxy that requires a login: CONNECT tunnels and absolute-URI HTTP requests."""

    def __init__(self):
        self.auth_seen: list[str | None] = []
        self.server = None
        self.port = 0

    async def start(self):
        self.server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def _client(self, reader, writer):
        # Like a real proxy, the connection stays open after a 407, for the retry with the login.
        while True:
            try:
                head = (await reader.readuntil(b"\r\n\r\n")).decode()
            except (asyncio.IncompleteReadError, ConnectionError):
                writer.close()
                return
            lines = head.split("\r\n")
            headers = {ln.split(":", 1)[0].lower(): ln.split(":", 1)[1].strip() for ln in lines[1:] if ":" in ln}
            self.auth_seen.append(headers.get("proxy-authorization"))
            if headers.get("proxy-authorization") == AUTH:
                break
            writer.write(b"HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm=\"proxy\"\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
        method, target, _ = lines[0].split(" ")
        if method == "CONNECT":
            host, port = target.rsplit(":", 1)
            up_r, up_w = await asyncio.open_connection(host, int(port))
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        else:
            rest = target.split("://", 1)[1]
            hostport, path = (rest.split("/", 1) + [""])[:2]
            host, port = (hostport.split(":") + ["80"])[:2]
            up_r, up_w = await asyncio.open_connection(host, int(port))
            kept = [ln for ln in lines[1:] if ln and not ln.lower().startswith("proxy-")]
            up_w.write(("\r\n".join([f"{method} /{path} HTTP/1.1", *kept]) + "\r\n\r\n").encode())
        await asyncio.gather(_relay(reader, up_w), _relay(up_r, writer))

    async def close(self):
        self.server.close()


async def _relay(src, dst):
    try:
        while data := await src.read(65536):
            dst.write(data)
            await dst.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        dst.close()


class Site(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    js_hits = 0

    def log_message(self, *a):
        pass

    def do_GET(self):
        # a kept-alive proxy connection relays later requests with their absolute URI
        if urlsplit(self.path).path == "/app.js":
            type(self).js_hits += 1
            body, ctype, extra = b"window.__app = 1;", "text/javascript", [("Cache-Control", "public, max-age=3600")]
        else:
            body, ctype, extra = b'<html><body>hi<script src="/app.js"></script></body></html>', "text/html", []
        self.send_response(200)
        for k, v in [("Content-Type", ctype), *extra]:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def site():
    Site.js_hits = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


async def test_forwarder_adds_the_login_to_a_tunnel_and_replaces_one_sent_by_the_client():
    upstream = UpstreamProxy()
    await upstream.start()
    echo = await asyncio.start_server(lambda r, w: _relay(r, w), "127.0.0.1", 0)
    fwd = ProxyForwarder(f"http://user-session-ab12:p%40ss@127.0.0.1:{upstream.port}")
    host, port = (await fwd.start()).split("//")[1].split(":")
    try:
        r, w = await asyncio.open_connection(host, int(port))
        target = f"127.0.0.1:{echo.sockets[0].getsockname()[1]}"
        w.write(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\nProxy-Authorization: Basic wrong\r\n\r\n".encode())
        await w.drain()
        assert (await r.readuntil(b"\r\n\r\n")).startswith(b"HTTP/1.1 200")
        w.write(b"opaque tls bytes")
        await w.drain()
        assert await r.readexactly(16) == b"opaque tls bytes"
        w.close()
        assert upstream.auth_seen == [AUTH]
    finally:
        await fwd.close()
        await upstream.close()
        echo.close()


async def _js_hits_over_two_loads(site: str, proxy: dict) -> int:
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=True)
        except PlaywrightError as e:
            pytest.skip(f"no launchable Chromium: {str(e).splitlines()[0]}")
        # "<-loopback>": Chrome otherwise sends 127.0.0.1 direct, past the proxy
        context = await browser.new_context(proxy={**proxy, "bypass": "<-loopback>"})
        page = await context.new_page()
        for _ in range(2):
            await page.goto(site + "/", wait_until="load")
            assert await page.evaluate("window.__app") == 1
        await browser.close()
    return Site.js_hits


async def test_through_the_forwarder_chrome_keeps_its_cache(site):
    upstream = UpstreamProxy()
    await upstream.start()
    fwd = ProxyForwarder(f"http://user-session-ab12:p%40ss@127.0.0.1:{upstream.port}")
    try:
        hits = await _js_hits_over_two_loads(site, {"server": await fwd.start()})
    finally:
        await fwd.close()
        await upstream.close()
    assert hits == 1
    assert upstream.auth_seen and all(a == AUTH for a in upstream.auth_seen)  # never challenged


async def test_with_the_login_in_playwright_the_cache_is_off(site):
    # Why the forwarder exists: if this starts passing with 1 hit, Playwright changed.
    upstream = UpstreamProxy()
    await upstream.start()
    try:
        hits = await _js_hits_over_two_loads(site, {"server": f"http://127.0.0.1:{upstream.port}",
                                                    "username": "user-session-ab12", "password": "p@ss"})
    finally:
        await upstream.close()
    assert hits == 2
