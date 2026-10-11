"""Google's "Before you continue to Google" consent dialog."""
import logging
import re

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

log = logging.getLogger("serp.consent")

# The dialog follows the browser's language: English, or Polish behind Polish exits with a
# pl-PL browser (BROWSER_LOCALE), German for de-DE.
REJECT_ALL = re.compile(r"^\s*(reject all|odrzuć wszystko|alle ablehnen)\s*$", re.I)


async def reject_consent(page: Page) -> bool:
    """The dialog covers Google pages for a context with no consent cookie (typical on UK/EU
    exits). Press its "Reject all" button, in the page or in a consent iframe, as a visitor
    would; this sets the consent cookie for the context. Returns whether it was there."""
    for frame in page.frames:
        btn = frame.get_by_role("button", name=REJECT_ALL).first
        try:
            if not await btn.is_visible():
                continue
            await btn.click(timeout=2000)
        except PlaywrightError:
            continue
        log.info("rejected consent dialog on %s", page.url)
        try:
            await btn.wait_for(state="hidden", timeout=3000)
        except PlaywrightError:
            pass
        await page.wait_for_load_state("domcontentloaded")
        return True
    return False
