"""Settings loaded from environment / .env."""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    api_key: str = ""
    headless: bool = False
    browser_channel: Literal["chromium", "chrome"] = "chromium"
    browser_executable_path: str = ""
    concurrency: int = 1
    block_resources: bool = True
    blocked_resource_types: str = "image,media,font"
    viewport_width: int = 1366
    viewport_height: int = 768
    # The screen the page reports. Unset, Playwright reports the viewport as the screen, and
    # the window (viewport + browser frame) comes out taller than the screen - impossible
    # on a real device. A common laptop/desktop screen, larger than the viewport.
    screen_width: int = 1920
    screen_height: int = 1080
    # en-US contexts take their language from Chrome itself (--lang=en-US) instead of
    # Playwright's locale emulation plus a hand-written Accept-Language header; the values
    # are then exactly what a real Chrome set to en-US produces. Other locales still use
    # emulation.
    native_en_us_languages: bool = True
    # The language Chrome itself is set to (--lang); contexts in this locale take their
    # languages from Chrome, others are emulated. en-US by default.
    native_locale: str = "en-US"
    # The browser's locale for every request, whatever the request's gl/hl (which still go
    # to Google unchanged): e.g. pl-PL behind Polish exit IPs. Empty = from gl/hl.
    browser_locale: str = ""
    results_per_page: int = 10
    nav_timeout_ms: int = 15000
    aio_appear_wait_ms: int = 1500
    # 12 s, not 8: on Polish exits (2026-10-07) Google loaded the sources' 'Show all' code
    # ~5 s after 'Show more', and an 8 s budget ended before the click could be confirmed
    # or retried (7 pages). Pages that expand quickly still finish in ~4-7 s.
    aio_max_wait_ms: int = 12000
    aio_click_timeout_ms: int = 4000  # per 'Show more/all' click attempt (still bounded by aio_max_wait_ms)
    request_deadline_ms: int = 25000
    max_retries: int = 0
    goto_concurrency: int = 16
    goto_timeout_ms: int = 3000
    min_delay_seconds: float = 10
    stop_on_block: bool = True
    max_live_requests_per_run: int = 30
    traffic_budget_mb: float = 0  # benchmark stops before exceeding this (0 = no budget)
    proxy_mode: Literal["none", "static", "list"] = "none"
    proxy_url: str = ""
    proxy_list_file: str = ""
    proxy_session_max_seconds: int = 0
    exit_ip_check_url: str = ""
    exit_ip_check_timeout_ms: int = 5000
    # Skip the exit-IP check before a request when this slot's IP was checked this
    # recently (the previous request's check after it). 0 = check before every request.
    exit_ip_recheck_seconds: float = 60
    # The browser's timezone (Date, Intl). Unset, the page reports the host's timezone
    # whatever the exit IP - the mobile run's US IPs carried Asia/Kolkata. With
    # TIMEZONE_FROM_EXIT_IP the timezone comes from the exit-IP check's answer, so
    # EXIT_IP_CHECK_URL must return JSON with a "timezone" (e.g. https://ipinfo.io/json);
    # TIMEZONE_ID (an IANA name, e.g. America/Chicago) is used when the check gives none.
    timezone_from_exit_ip: bool = True
    # Browser-wide proxy when PROXY_MODE is not none. Page traffic uses each context's own
    # proxy, but Chrome's background services (push messaging :5228, component updates,
    # sign-in checks) use the browser-wide one - with none they went straight out from the
    # host's IP (leak check on the US VM: 7 direct Google connections). A dead address makes
    # them fail instead. Empty = no browser-wide proxy.
    launch_proxy: str = "http://127.0.0.1:9"
    timezone_id: str = ""
    # Build each slot's context (and run its first exit-IP check) at startup, so
    # the first request doesn't pay for it.
    prewarm_slots: bool = True
    # How a Google results page is opened: "url" goes straight to the requested /search URL;
    # "typed" opens the Google homepage, types the query into the search box with per-key
    # delays and presses Enter, like a person (the approach of web-agent-master/google-search).
    # Typed mode only applies to page 1 of a query (no `start` offset) and adds ~1-3 s.
    search_mode: Literal["url", "typed"] = "url"
    typed_key_delay_min_ms: int = 30
    typed_key_delay_max_ms: int = 90
    # Typed search: pause on the homepage (random, within this range) before clicking the
    # search box, like a visitor who looks at the page first. 0 = no pause.
    typed_warmup_min_ms: int = 0
    typed_warmup_max_ms: int = 0
    # web-agent-master/google-search techniques (POC, opt-in): "fingerprint" patches navigator/
    # window/WebGL/screen values with init scripts; "state_file" reuses cookies saved after a
    # successful search (storage state) and saves them again after each success.
    repo_fingerprint: bool = False
    repo_state_file: str = ""
    debug_artifacts: bool = True
    debug_screenshot_on_success: bool = False
    artifacts_dir: str = "artifacts"


@lru_cache
def get_settings() -> Settings:
    return Settings()
