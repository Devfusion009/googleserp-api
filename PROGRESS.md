# PROGRESS

## Phase 1 — Setup + first look (1 live request) — DONE, but BLOCKED

### Done
- Project skeleton: `app/`, `app/parsers/`, `bench/corpora/`, `scripts/`, `tests/fixtures/`, `artifacts/`, `reports/` (last two git-ignored).
- Python 3.12.3 venv (`.venv`), dependencies from `requirements.txt` installed (FastAPI 0.141, Playwright 1.63, selectolax 0.4, pydantic 2.13, pydantic-settings 2.15, httpx 0.28, pytest 9.1).
- Playwright Chromium installed. OS: Linux (display available, so headed mode works).
- `app/config.py` (pydantic-settings), `.env.example`, `.env` (git-ignored), `.gitignore`.
- `scripts/first_look.py`: one visible-browser request, 1366x768, locale en-US, Accept-Language en-US. No clicks, waits 8 s, saves HTML + full-page screenshot.

### Result of the single live request (2026-09-24 02:35 local)
- URL sent: `https://www.google.com/search?q=how%20does%20dns%20work&gl=us&hl=en`
- Google redirected straight to `https://www.google.com/sorry/index?...` (0.68 s).
- Page: reCAPTCHA + "Our systems have detected unusual traffic from your computer network."
- Google saw the request coming from an IPv6 address (2401:4900:…, Indian mobile/ISP range).
- Artifacts: `artifacts/20260924_023537_first_look/` (page.html, screenshot.png).
- Per hard rules: detected, recorded, stopped. No retry, no CAPTCHA interaction by code.

### Decisions
- Project root is this repo folder (not a nested `serp-api/`).
- Default browser: bundled Chromium, headed (HEADLESS=false).

### Open questions
- How to proceed after the block: (a) wait ~1 hour and retry once, (b) try `BROWSER_CHANNEL=chrome` (installed Google Chrome, still no stealth), (c) use pages copied from the user's normal Chrome as fixtures, or a combination.
