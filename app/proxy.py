"""Proxy providers. Switch with PROXY_MODE=none|static|list (config only)."""
import itertools
import threading
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from .config import Settings


def mask_proxy(url: str | None) -> str:
    if not url:
        return "none"
    p = urlsplit(url)
    user = f"{p.username[:3]}***@" if p.username else ""
    return f"{p.scheme}://{user}{p.hostname}:{p.port}"


def to_playwright(url: str) -> dict:
    p = urlsplit(url)
    out = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
    if p.username:
        out["username"] = p.username
    if p.password:
        out["password"] = p.password
    return out


class ProxyProvider:
    rotates = False

    def next(self, country: str | None = None) -> str | None:
        raise NotImplementedError


class NoProxy(ProxyProvider):
    def next(self, country=None):
        return None


class StaticProxy(ProxyProvider):
    def __init__(self, url: str):
        if not url:
            raise ValueError("PROXY_MODE=static needs PROXY_URL")
        self.url = url

    def next(self, country=None):
        return self.url


class ListProxy(ProxyProvider):
    """Round-robin over one proxy URL per line. `country` is accepted for future
    provider-specific routing (e.g. a '{country}' placeholder in the URL)."""
    rotates = True

    def __init__(self, path: str):
        lines = [l.strip() for l in Path(path).read_text().splitlines()]
        urls = [l for l in lines if l and not l.startswith("#")]
        if not urls:
            raise ValueError(f"no proxies in {path}")
        self._cycle = itertools.cycle(urls)
        self._lock = threading.Lock()

    def next(self, country=None):
        with self._lock:
            url = next(self._cycle)
        return url.replace("{country}", (country or "us").lower())


PROXY_PROVIDERS: dict[str, Callable[[Settings], ProxyProvider]] = {
    "none": lambda s: NoProxy(),
    "static": lambda s: StaticProxy(s.proxy_url),
    "list": lambda s: ListProxy(s.proxy_list_file),
}


def make_provider(s: Settings) -> ProxyProvider:
    return PROXY_PROVIDERS[s.proxy_mode](s)
