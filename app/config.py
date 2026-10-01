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
    results_per_page: int = 10
    nav_timeout_ms: int = 15000
    aio_appear_wait_ms: int = 1500
    aio_max_wait_ms: int = 8000
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
