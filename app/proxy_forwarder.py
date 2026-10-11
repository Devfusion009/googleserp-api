"""A local proxy that adds the upstream proxy's login, so Chrome sees a proxy without one.

Why: Playwright answers a proxy's login challenge by intercepting every request
(Fetch domain), and it turns the browser's HTTP cache off while it intercepts
(crNetworkManager: request interception is on whenever credentials are set). With
the cache off, every search in a session downloads Google's ~1-2 MB of scripts
again (Poland run 2026-10-10: 70% of all traffic, and the seconds it takes on a
residential exit). This forwarder listens on 127.0.0.1, forwards each connection
to the upstream proxy and adds Proxy-Authorization to its first request - the same
approach as Apify's proxy-chain ("anonymizeProxy").

HTTPS (CONNECT) is relayed as an opaque tunnel after the CONNECT line, so the
forwarder never sees page content. A plain-HTTP request is sent with
"Connection: close", so each one arrives on a new connection and gets the header.
"""
import asyncio
import base64
import logging
from urllib.parse import unquote, urlsplit

log = logging.getLogger("serp.forwarder")

MAX_HEADER_BYTES = 64 * 1024
DROP_HEADERS = (b"proxy-authorization:", b"proxy-connection:", b"connection:")


class ProxyForwarder:
    def __init__(self, upstream: str):
        p = urlsplit(upstream)
        self.host, self.port = p.hostname, p.port or 8080
        login = f"{unquote(p.username or '')}:{unquote(p.password or '')}"
        self._auth = b"Proxy-Authorization: Basic " + base64.b64encode(login.encode()) + b"\r\n"
        self._server: asyncio.base_events.Server | None = None
        self._tasks: set[asyncio.Task] = set()
        self.url = ""

    async def start(self) -> str:
        self._server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.url = f"http://127.0.0.1:{self._server.sockets[0].getsockname()[1]}"
        return self.url

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        for t in list(self._tasks):
            t.cancel()

    def _rewrite(self, head: bytes) -> bytes:
        lines = head.split(b"\r\n")
        connect = lines[0].upper().startswith(b"CONNECT ")
        kept = [ln for ln in lines[1:] if ln and not ln.lower().startswith(DROP_HEADERS)]
        extra = [] if connect else [b"Connection: close"]
        return b"\r\n".join([lines[0], *kept, *extra]) + b"\r\n" + self._auth + b"\r\n"

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        self._tasks.add(task)
        up_writer = None
        try:
            try:
                head = await reader.readuntil(b"\r\n\r\n")
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
                return
            if len(head) > MAX_HEADER_BYTES:
                return
            try:
                up_reader, up_writer = await asyncio.open_connection(self.host, self.port)
            except OSError as e:
                log.warning("upstream proxy unreachable: %s", e)
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return
            up_writer.write(self._rewrite(head[:-4]))
            await up_writer.drain()
            await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))
        finally:
            for w in (writer, up_writer):
                if w is not None:
                    w.close()
            self._tasks.discard(task)


async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while data := await src.read(65536):
            dst.write(data)
            await dst.drain()
    except (ConnectionError, asyncio.CancelledError, OSError):
        pass
    finally:
        try:
            if dst.can_write_eof():
                dst.write_eof()
        except (OSError, RuntimeError):
            pass
