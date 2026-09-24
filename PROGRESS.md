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

## Fixtures — DONE (16/16, captured 2026-09-24)

All 16 corpus pages captured via the user's normal (signed-in) Chrome, automated with
the claude-in-chrome browser extension (not the Playwright fetcher — that's still
blocked by the CAPTCHA from Phase 1). For each: navigated, checked for an AI Overview,
clicked "Show more" and any sources "Show all" fully, downloaded the live DOM as HTML
(`document.documentElement.outerHTML`), and stitched scroll-position screenshots into
one PNG per fixture. Files in `tests/fixtures/<slug>.html` + `.png`, manifest updated.

AI Overview present (11): t_mobile, mobile, apple, best_cell_phone_plans,
car_insurance_quotes, crm_software, how_does_dns_work, why_is_the_sky_blue,
best_supplements_for_sleep, how_to_replace_a_kitchen_faucet_cartridge_delta_1400_series,
difficult_flights_to_brussels_from_shanghai.
No AI Overview (5): wikipedia, chase_bank_login, coffee_shops_near_seattle,
plumber_austin_tx, eiffel_tower — all plausible (navigational or local-pack queries).

Bonus real fixtures found along the way (useful for the "skip" rules in Phase 3):
- `coffee_shops_near_seattle`, `plumber_austin_tx`: local pack + map + "Businesses" module.
- `plumber_austin_tx`: top/bottom text ads ("Sponsored Results"), one with an "Have AI get prices" button.
- `eiffel_tower`: image carousel, "Sponsored Tickets & Tours" carousel (prices in INR - Google
  used the real browsing IP's currency despite gl=us&hl=en), Knowledge Panel, world-map "Places"
  block, short-videos carousel, "Discussions and forums" module.
- `difficult_flights_to_brussels_from_shanghai`: flights module + "Flight status" module (both
  must be skipped per the rules), AI Overview with inline source chips (no side "Show all" panel
  this time — Google renders AIO sources two different ways).
- `how_to_replace_a_kitchen_faucet_cartridge_delta_1400_series`: AI Overview correctly points
  out the "1400 series" is a tub/shower valve, not a kitchen faucet part; one organic result
  showed a "Missing: kitchen | Show results with: kitchen" line (a real corrections-adjacent case
  to check against the `corrections` field rule).

Caveat: captured while signed in to a Google account (not incognito), so a few pages show
"Results are personalized" and a location note. Structure/fields should still be representative;
noted here in case the client asks why ads/results don't match a clean/incognito session.

Tooling notes for later fixture refreshes:
- `scripts/save_fixture.py`: moves the newest downloaded HTML + screenshot from
  `~/Downloads`, `~/Desktop/Downloads`, `~/Pictures/Screenshots` or the home directory
  into `tests/fixtures/<slug>.{html,png}` (which directory Chrome uses varies by tab/profile).
- `scripts/stitch_screenshots.py`: stacks scroll-position screenshots (`--since <unix ts>`)
  into one tall PNG for a fixture (small vertical overlap between shots is normal).
- Reliability quirk observed this session: after a tab has done one HTML download via
  `URL.createObjectURL` + anchor click, a second download attempt in the *same* tab silently
  fails about half the time (no dialog, no error, file never appears) and can also stall the
  CDP screenshot channel until the download resolves. Workaround: one fresh tab per query,
  download the HTML once per tab, never retry a failed download in the same tab — open a new
  one instead. Filed as feedback.

## Phase 3 — Parsers — IN PROGRESS (organic, ads, AIO, misc fields done; knowledge_panel not started)

No live requests. Built and tested against the 16 real fixtures from Phase 2.

### Done
- `app/models.py`: pydantic models matching the client's JSON exactly (SerpRequest, OrganicItem/SubLink, AiOverview/AioSection/AioSource, KnowledgePanel, PageResult, SerpResponse).
- `app/parsers/misc.py`: text-cleanup helpers (`clean_text`, `clean_prose` for punctuation spacing, `dedupe_consecutive` for the aria-hidden duplicate-text problem) plus `number_of_results` (from `#result-stats`), `suggestions` (from the *last* "Related searches"/"People also search for" block inside `#botstuff` - a knowledge panel can have an earlier one about related entities, not searches), `corrections` (untested - no fixture triggers it).
- `app/parsers/organic.py`: walks every `<a><h3>` inside `#rso`, climbs to the nearest ancestor with `data-hveid` for the per-result boundary. URL resolution: real hrefs are used directly; `/url?q=` is unwrapped; Google's newer opaque `/goto?url=<token>` redirect (seen on ~1/3 of fixtures, cannot be decoded per the no-reverse-engineering rule) falls back to the visible `<cite>` breadcrumb text rebuilt into a URL - real on-page text, but sometimes only the site root if Google didn't show a fuller breadcrumb; logged as a parse warning each time. Sitelinks (`sub_links`) picked up when they're real anchors (jump-links, some sitelink rows); Google's "Web Result with Site Links" table layout (t_mobile.html) has *no hrefs in the DOM at all* for its sitelinks - `sub_links` is honestly empty there, not guessed.
- `app/parsers/ads.py`: every `[data-text-ad]` inside `#tads`/`#bottomads`. Ad hrefs are the real destination directly; ad sitelinks sometimes route through `/aclk?...&adurl=<real_url>` and we read the `adurl` param.
- `app/parsers/aio.py`: the AI Overview root (`classify.find_aio_root`) walked in document order. Section headings = `role=heading[aria-level="3"]`. Paragraphs = `.n6owBd`. Bullets = plain `<li>`. Sources = `<li class="h7wxwc">` (title `.gpZmoc`, url from `a.vIWmYe` - direct real href, snippet `.hxIQcc`); this class showed up in exactly the 11/16 fixtures that have an AI Overview and nowhere else, so it's a solid hook. The walk stops the moment it reaches the sources list, so the paragraph/bullet stream never picks up citation-panel text. Small inline citation pills (favicon + "Publisher +1") are stripped before reading text, or intro/section text would end with junk like "... tasks . Microsoft +1".
- `scripts/demo_parse.py`: assembles one fixture into the exact response JSON (minus `knowledge_panel`, always null for now) so it can be eyeballed against the screenshot. Not the real API - that's Phase 4.
- All 26 existing tests still pass; no new tests added yet for the parsers (next step, see below).

### Verified against screenshots (3 examples, see chat)
- `how_does_dns_work`: organic (9), AI Overview (intro + 3 sections + 3 sources) - matches the screenshot closely.
- `car_insurance_quotes`: paid (2, incl. one duplicate ad shown twice on the real page), organic (10), AI Overview (intro + 2 sections + 9 sources, matching the fully-expanded "Show all") - matches.
- `wikipedia`: organic only, `ai_overview: null` correctly, sitelinks null where Google gives no real href (the language-switcher row) - matches.

### Known imperfect cases (real, not hidden)
- Video-type organic results (e.g. the YouTube result on `how_does_dns_work`) pick up extra chrome (chapter timestamps, "8 key moments...", repeated view-count line) in `content` - that layout doesn't use the same content wrapper as a plain web result. Needs its own case.
- Google's "Web Result with Site Links" layout (seen on `t_mobile`, `mobile`, `apple`, `best_cell_phone_plans`, `chase_bank_login`, `wikipedia` - fixtures using the `/goto` redirect style) falls back to a cruder snippet-by-subtraction and sometimes leaves in "About this result" or a stray split word (e.g. a bolded "T-Mobile" rendered as "T - Mobile"). Lower priority since `url`/`title` are still correct.
- `corrections` is unverified - no query in the corpus triggers "Did you mean"/"Showing results for".
- `knowledge_panel` is not implemented yet - always `null`. `eiffel_tower.html` and `apple.html`/`t_mobile.html` (via `#rhs`) have one; needs its own investigation pass.

### Open questions for the client (collect for the README "assumptions" section)
- Is the reconstructed-from-breadcrumb URL (used only when Google's own `/goto` redirect can't be decoded) acceptable, given it's occasionally just the site root instead of the deep link?
- Is a slightly noisier `content` field acceptable for video-type organic results, or should those be cleaned up before Phase 4?

## Phase 3 — Parsers — DONE

### Added since last update
- `app/parsers/knowledge_panel.py`: title/subtitle from a repeated `div.WcZOu` header stack, description + source_url from `[data-attrid="description"] .kno-rdesc` (the attribution link's href, real and direct), facts from every `[data-attrid^="kc:/"]` that has a `.w8qArf` label. **Verified against exactly one real fixture** (`eiffel_tower.html`) - it's the only one of the 16 with a traditional entity panel; `apple.html`/`t_mobile.html` have an empty `#rhs` placeholder (their "About X" box is a different, AI-generated element next to the AI Overview, out of scope for this field) - correctly returns `null` there. Treat these hooks as provisional until a second real KP page confirms them.
- `tests/test_parsers.py`: 43 new tests (69 total) against the real fixtures - every fixture has non-empty organic, DNS/Wikipedia first-result title+url exact match, every AIO-present fixture has intro/sections/sources (or a documented empty-sources exception, see below), every no-AIO fixture has none, ads present/absent as expected, knowledge panel exact match on eiffel_tower and null on the placeholder pages, suggestions correctly skip the knowledge panel's own "People also search for" carousel.
- `scripts/demo_parse.py` now fills in `knowledge_panel` too.

### New real limitation found by the tests (not previously known)
Google's opaque `/goto?url=<token>` link wrapper (documented for organic results) also appears on **AI Overview source cards** on 4 of the 11 AIO fixtures (apple, mobile, t_mobile, best_cell_phone_plans) - and unlike organic results, these source cards have **no visible cite/breadcrumb text to fall back to** (just a publisher name like "YouTube · Some Channel"). Per the no-reverse-engineering rule, we can't decode the token, so `ai_overview.sources` is correctly empty on those 4 pages even though the AI Overview clearly shows source cards on screen. `intro`/`sections` are unaffected (they don't depend on that link). Flagging this for the client - it's a real gap, not a bug we're hiding.

### All parsers now covered
organic, ads, ai_overview (intro/sections/sources), knowledge_panel, number_of_results, suggestions, corrections (still unverified - no fixture triggers it). 69/69 tests pass.

### Next: Phase 4 (FastAPI app + full test suite for the API layer)

## Phase 4 — FastAPI app + tests — DONE

No live requests. Smoke-tested the real server startup/shutdown (real Playwright
browser launches and closes cleanly) and one invalid-url request through it -
no request reached Google.

### Done
- `app/main.py`: `POST /serp`, `GET /health` (no API key needed). Validates the
  URL first (400 `invalid_url`, no fetch attempted). Pages: `ceil(results/10)`,
  page 1 untouched, `&start=10*n` after - built via `urls.page_url` (Phase 2).
  Any page that doesn't come back `ok` stops pagination immediately and returns
  that page's error with `results: []` (a later page failing discards earlier
  successful ones, per the "results:[] on error" contract). `requests_used`
  sums `timings["attempt"]` (retries included) across every page fetched.
  `return_json: false` returns page 1's raw HTML as `text/html`. Debug headers
  (`X-Request-Id`, `X-Classification`, `X-AIO-State`, `X-Timings`) set on every
  response, success or error. `X-API-Key` enforced only when `API_KEY` is set.
  A malformed body (missing `url`, wrong types) gets the client's own error
  envelope at 400, not FastAPI's default 422 shape.
- Testability: `get_fetcher`/`get_app_settings` are FastAPI dependencies, not
  direct `app.state` reads, so tests override them and never touch
  `app.state.browsers` - no real Playwright browser is ever launched by the
  test suite.
- `tests/test_api.py`: 17 tests, fetcher mocked with a `FakeFetcher` - success
  shape, the difficult URL reaching the fetcher byte-for-byte, multi-page
  pagination (`results=15` -> 2 fetcher calls, second with `&start=10`),
  invalid URL rejected pre-fetch, malformed body -> 400 not 422, every failure
  classification -> correct HTTP status + error code + empty `results`, a
  second-page failure discarding the first page, `return_json: false`, API key
  required/not-required, debug headers present.
- All 86 tests pass (26 Phase 2 + 43 Phase 3 + 17 Phase 4).

### Open question for the client
- On a >10-results request where an early page succeeds but a later page fails
  (e.g. gets CAPTCHA'd), we currently discard the successful early page(s) and
  report the failure with `results: []`, since the contract says `results: []`
  on any error. An alternative would be returning the successful pages with a
  partial-failure flag. Confirm which the client's benchmark expects.

### Next: Phase 5 (local benchmark, max 20 live requests: 15 mixed + 5 difficult)

## Phase 5 — Local benchmark — DONE (blocked, as expected)

### Built (offline-tested before any live request)
- `bench/run_bench.py`: HTTP client against the running API, `--corpus mixed|difficult|both`, `--repeat`, `--limit`, `--concurrency` (default 1), `--min-delay` (default MIN_DELAY_SECONDS, measured from when the previous request *finished*), refuses > MAX_LIVE_REQUESTS_PER_RUN without `--allow-more`, stops at the first `blocked_captcha`. Writes `reports/<run_id>/responses.jsonl` + `report.md`: per corpus valid rate + counts per classification, P50/P95/max over ALL requests (nearest-rank) with PASS/FAIL vs 98% / 2000 ms, AI Overview appeared/complete/avg sources per query, average stage timings (from `X-Timings`), top failure reasons with artifact paths. Local-run label on every report.
- Error responses now also carry `X-AIO-State`, `X-Timings` and a new `X-Artifact-Dir` header (debug-only, body unchanged).
- `tests/test_bench.py`: 7 tests (nearest-rank, planning, cap refusal, header parsing via in-process ASGI, summary/report incl. failures counted in latency, stop-at-first-CAPTCHA). 93 tests total, all passing.

### Live run (user-approved, 2026-09-24 20:32, bundled Chromium, visible browser, no proxy)
- Planned: 15 mixed, then 5 difficult. **Actual: 1 request.**
- Request 1 (`t-mobile`): redirected to `/sorry/` - "unusual traffic from your computer network" (reCAPTCHA). Classified `blocked_captcha`, 1493 ms wall. Artifact: `artifacts/20260924_203228_t_mobile/`.
- Run stopped immediately per the stop-at-first-CAPTCHA rule. The difficult corpus was **not run** (same IP, still flagged).
- Report: `reports/20260924_203226/report.md` (git-ignored). Mixed: valid 0/1 (0.0%) FAIL. The "P95 1493 ms PASS" in that report is technically correct per the spec (failures count), but meaningless - it's the time to an instant CAPTCHA. The report now adds a caution line whenever the valid rate misses target (added after this run; the saved report predates it).
- Conclusion: this home IP (Indian ISP, IPv6) is blocked for automated Chromium regardless of pacing - 2 of 2 attempts ~18 h apart. Local latency/valid-rate numbers cannot be produced from here; they need the client's US residential proxies (`PROXY_MODE=static|list`, config only).

### Fixed because of the live run
- The server log had none of the app's own lines (URL sent, final URL, proxy used, classification, timings): uvicorn only configures its own loggers. `app/main.py` now attaches a handler to the `serp` logger at import.

### Still unverified live (needs an unblocked IP)
- The fetcher's AI Overview wait/expand logic (appear -> stable -> click "Show more"/"Show all") has never run against a live page. Parsers are verified against real saved pages; the waiting/clicking is not.
