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

## Phase 2 — Fetcher, classifier, fixtures — DONE (fixtures pending from user)

### Decision (user, 2026-09-24): option 3
Home IP is CAPTCHA-blocked, so parser fixtures come from the user's normal Chrome
(DevTools "Copy outerHTML" after clicking "Show more"/"Show all" + full-size screenshot).
Zero live requests made in this phase.

### Done
- `app/urls.py`: URL validation (host google.com/www.google.com, path /search, q= required; no re-encoding), extra-page URLs (`&start=10`, page 1 untouched), `/url?q=` unwrapping, `#:~:text=` stripping.
- `app/proxy.py`: NoProxy / StaticProxy / ListProxy (round-robin, optional `{country}` placeholder), masked logging.
- `app/browser.py`: one warm browser, pool of CONCURRENCY slots (context+page each), per-context proxy and locale, image/media/font blocking (scripts/CSS never blocked), 1366x768.
- `app/classify.py`: pure `classify_page(final_url, html, organic_count)` -> ok / blocked_captcha / consent_wall / degraded_page / aio_incomplete, plus aio_state absent/complete/incomplete.
- `app/fetcher.py`: navigate (domcontentloaded), early classify, wait #search/#rso, wait for AI Overview (appear -> not busy + text stable 300 ms -> click "Show more"/"Show all" buttons without href -> check URL unchanged), capture HTML, artifacts, stage timings, deadline, retries only for timeout/network_error.
- `scripts/capture_fixtures.py`: `--check` (default) lists missing fixtures with exact URLs; `--live` fetches paced with the real fetcher (for later, with proxies).
- `bench/corpora/mixed.txt` (15 URLs) and `difficult.txt` (exact string).
- Classifier fixtures: `real_captcha_sorry.html` (the real Phase 1 page, IP and IP-derived tokens redacted) + `synthetic_*` files.
- Tests: 26 passing (URL rules, classifier cases, difficult URL passed to the browser byte-for-byte).

### Not yet verifiable locally
- The AI Overview wait logic (loading signs, "Show more" clicking) cannot be tested live while the IP is blocked. Pages copied from Chrome are already fully loaded, so they test parsers, not the wait logic. Loading-state hooks in `classify.py` / `fetcher.py` are best guesses until a live page is seen.

### Open questions
- If Google shows "Can't generate an AI Overview right now", we classify it as aio_incomplete (failure). Client to confirm.
- Manual fixtures come from an Indian IP with gl=us, so the page may differ a little from what a US proxy gets (ads, local results).
