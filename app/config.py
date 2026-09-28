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
    request_deadline_ms: int = 25000
    max_retries: int = 0
    goto_concurrency: int = 16
    goto_timeout_ms: int = 3000
    min_delay_seconds: float = 10
    stop_on_block: bool = True
    max_live_requests_per_run: int = 30
    proxy_mode: Literal["none", "static", "list"] = "none"
    proxy_url: str = ""
    proxy_list_file: str = ""
    debug_artifacts: bool = True
    artifacts_dir: str = "artifacts"


@lru_cache
def get_settings() -> Settings:
    return Settings()
