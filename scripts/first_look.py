"""Phase 1: one live request in a visible browser. Saves HTML + screenshot."""
import asyncio
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.async_api import async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402

QUERY = "how does dns work"


async def main() -> None:
    s = get_settings()
    url = f"https://www.google.com/search?q={quote(QUERY, safe='')}&gl=us&hl=en"
    out = Path(s.artifacts_dir) / f"{time.strftime('%Y%m%d_%H%M%S')}_first_look"
    out.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        kwargs = {"headless": s.headless}
        if s.browser_channel == "chrome":
            kwargs["channel"] = "chrome"
        browser = await p.chromium.launch(**kwargs)
        ctx = await browser.new_context(
            viewport={"width": 1366, "height": 768}, locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        page = await ctx.new_page()
        print("URL sent:", url)
        t0 = time.perf_counter()
        await page.goto(url, wait_until="domcontentloaded", timeout=s.nav_timeout_ms)
        print(f"domcontentloaded after {time.perf_counter()-t0:.2f}s, final URL: {page.url}")
        # Look only; no clicking. Give JS time to render the AI Overview.
        await page.wait_for_timeout(8000)
        (out / "page.html").write_text(await page.content(), encoding="utf-8")
        await page.screenshot(path=str(out / "screenshot.png"), full_page=True)
        print("Saved to", out)
        await browser.close()


asyncio.run(main())
