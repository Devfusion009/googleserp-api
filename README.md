# Google SERP API

A small HTTP API that loads a Google search results page in a real browser
(Playwright + Chromium) and returns it as structured JSON: paid ads, organic
results, the AI Overview (full text and every source), the knowledge panel,
the result count, related searches and spelling corrections.

It never uses third-party SERP/scraping services, caches or any other data
source, never solves or works around CAPTCHAs, and never makes data up: if
something isn't on the page it comes back `null`/empty, and a blocked,
degraded or incomplete page is reported as a failure, not a result.

## Status (read this first)

| Area | State |
|---|---|
| API (`POST /serp`, `GET /health`), exact response schema | Done, 95 tests passing |
| Parsers (organic, ads, AI Overview, knowledge panel, count, suggestions) | Done, tested against 16 real saved Google pages |
| Proxy support | Done - switch on with config only (see [Proxies](#proxies)) |
| Benchmark client | Done - see [Benchmark](#benchmark) |
| **Live performance numbers** | **Not available yet.** The development machine's IP (India, no proxy) gets Google's "unusual traffic" CAPTCHA on the very first request, every time. The one local benchmark run stopped after 1 request (`blocked_captcha`). Valid-rate and latency against the client's targets can only be measured through the client's US residential proxies. |
| Live AI Overview wait/expand logic | Written, never exercised live (same reason). Parsers are verified; the in-browser waiting/clicking is not. |

Details, decisions and history are in [`PROGRESS.md`](PROGRESS.md).

## Setup

Requires Python 3.11+ (developed on 3.12).

**Linux / macOS**

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
cp .env.example .env
```

On a Linux server without a display, set `HEADLESS=true` in `.env`, or run under
`xvfb-run`. Playwright may also ask for system libraries:
`.venv/bin/playwright install-deps chromium` (needs sudo).

**Windows (PowerShell)**

```powershell
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\playwright install chromium
copy .env.example .env
```

## Run

```bash
.venv/bin/python run.py          # Windows: .venv\Scripts\python run.py
```

`run.py` reads `HOST`/`PORT` from `.env` (default `127.0.0.1:8000`). On Windows it
sets the Proactor event loop Playwright needs and never uses `--reload` (that
combination is what causes `NotImplementedError` when the browser launches).
`uvicorn app.main:app` also works on Linux/macOS.

The browser starts once at startup and stays warm; pages are reused between
requests.

```bash
curl -s http://127.0.0.1:8000/health
# {"status":"ok"}

curl -s -X POST http://127.0.0.1:8000/serp \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.google.com/search?q=how%20does%20dns%20work&gl=us&hl=en","results":10,"country":"US","language":"en","return_json":true}'
```

PowerShell:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/serp -ContentType 'application/json' `
  -Body '{"url":"https://www.google.com/search?q=how%20does%20dns%20work&gl=us&hl=en","results":10}'
```

If `API_KEY` is set, add `-H 'X-API-Key: <key>'`. `/health` never needs a key.

## API

**Request** - `POST /serp`

| field | meaning |
|---|---|
| `url` | A Google search URL (`google.com` or `www.google.com`, path `/search`, must have `q=`). Sent to Google **exactly as given** - never re-encoded, reordered or "fixed" (the difficult URL's `hl=us` stays). Anything else -> 400 `invalid_url`, and nothing is fetched. |
| `results` | `10` = page 1 only. More than 10 fetches extra pages by appending `&start=10`, `&start=20`, ... to a copy of the URL (page 1 is untouched; `num=` is never used). |
| `country`, `language` | Used only for the browser locale / `Accept-Language` (e.g. `en-US`) and, with a provider that supports it, proxy country. Never change the URL. |
| `return_json` | `false` returns page 1's rendered HTML as `text/html`. |

**Response** - exactly the client's shape: `status_code`, `requests_used`,
`elapsed_time` (server-side ms), `results` (one object per page: `page`, `paid`,
`organic`, `ai_overview`, `knowledge_panel`, `number_of_results`, `suggestions`,
`corrections`), `error`, `error_message`.

| `status_code` | `error` | when |
|---|---|---|
| 200 | `null` | valid result |
| 400 | `invalid_url` | URL not allowed, or malformed request body |
| 429 | `blocked_captcha` | Google CAPTCHA / "unusual traffic" (`/sorry/`) |
| 502 | `consent_wall` | "Before you continue" consent page |
| 502 | `degraded_page` | JavaScript-required notice, basic-HTML version, no results container, or zero organic results |
| 502 | `aio_incomplete` | an AI Overview is on the page but didn't finish loading/expanding in time, or Google shows its "can't generate an AI Overview right now" message |
| 502 | `parse_error` | the page loaded but parsing crashed |
| 502 | `network_error` | browser/network failure |
| 504 | `timeout` | navigation or the overall request deadline timed out |

On any error `results` is `[]`. With `results > 10`, if any page fails the whole
request fails (see [Assumptions](#assumptions-to-confirm-with-the-client)).
`requests_used` counts every Google page load for the call, retries included.

**Debug headers** (never in the JSON body): `X-Request-Id`, `X-Classification`,
`X-AIO-State` (`absent` / `complete` / `incomplete`), `X-Timings` (JSON: `nav_ms`,
`results_ms`, `aio_ms`, `total_ms`, `attempt`), `X-Artifact-Dir` (saved HTML +
screenshot for this request, when `DEBUG_ARTIFACTS=true`).

## Configuration

All settings come from `.env` (see `.env.example`) or environment variables.

| variable | default | meaning |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8000` | where `run.py` listens (also the benchmark's default target) |
| `API_KEY` | empty | if set, `POST /serp` requires `X-API-Key: <value>` |
| `HEADLESS` | `false` | `true` for servers without a display |
| `BROWSER_CHANNEL` | `chromium` | `chromium` (Playwright's bundled build) or `chrome` (installed Google Chrome). No stealth/fingerprint patches either way. |
| `CONCURRENCY` | `1` | number of browser pages kept open and used in parallel |
| `BLOCK_RESOURCES` | `true` | skip images, media and fonts (scripts and stylesheets are never blocked - the AI Overview needs them) |
| `NAV_TIMEOUT_MS` | `15000` | navigation timeout, and max wait for the results container |
| `AIO_APPEAR_WAIT_MS` | `1500` | how long to wait for an AI Overview to appear once results are visible |
| `AIO_MAX_WAIT_MS` | `8000` | max time for a present AI Overview to finish loading and expand; beyond this -> `aio_incomplete` |
| `REQUEST_DEADLINE_MS` | `25000` | hard cap per page load -> `timeout` |
| `MAX_RETRIES` | `0` | retries for `timeout` / `network_error` only - never for a CAPTCHA |
| `MIN_DELAY_SECONDS` | `10` | minimum gap between live requests in the benchmark and fixture tools |
| `STOP_ON_BLOCK` | `true` | benchmark and fixture capture stop at the first CAPTCHA (set `false` only with a rotating proxy list) |
| `MAX_LIVE_REQUESTS_PER_RUN` | `30` | the benchmark / fixture tools refuse bigger runs unless `--allow-more` |
| `PROXY_MODE` | `none` | `none`, `static` or `list` |
| `PROXY_URL` | empty | for `static`: `http://user:pass@host:port` |
| `PROXY_LIST_FILE` | empty | for `list`: file with one proxy URL per line, used round-robin |
| `DEBUG_ARTIFACTS` | `true` | save every page's HTML + full-page screenshot to `ARTIFACTS_DIR/<timestamp>_<query>/` |
| `ARTIFACTS_DIR` | `artifacts` | where artifacts go (git-ignored) |

## Proxies

Proxies are per browser context and need no code change:

```ini
# one proxy for everything
PROXY_MODE=static
PROXY_URL=http://USER:PASS@proxy.example.com:8000

# or a list, rotated per request
PROXY_MODE=list
PROXY_LIST_FILE=proxies.txt
```

In a list file, a literal `{country}` in a line is replaced with the request's
`country` in lowercase (e.g. `http://user-country-{country}:pass@host:port`), for
providers that select the exit country through the username. Credentials are
masked in logs (`http://use***@host:port`); every request logs which (masked)
proxy it used.

## Benchmark

Start the API, then in a second terminal:

```bash
.venv/bin/python bench/run_bench.py --corpus mixed              # 15 queries
.venv/bin/python bench/run_bench.py --corpus difficult --repeat 5
.venv/bin/python bench/run_bench.py --corpus both --limit 3     # first 3 of each
```

Options: `--corpus mixed|difficult|both`, `--repeat N`, `--limit N`,
`--concurrency N` (default 1), `--min-delay S` (default `MIN_DELAY_SECONDS`),
`--allow-more`, `--base-url`, `--api-key`.

It calls the API over HTTP exactly like the client will and measures
client-side wall-clock time per request. Each run writes
`reports/<run_id>/responses.jsonl` (every response) and `report.md`, per corpus:
valid-result rate with counts per classification; P50 / P95 / max latency over
**all** requests including failures (nearest-rank), with PASS/FAIL against
>= 98% and <= 2000 ms; AI Overview appeared/complete/average sources per query;
average stage timings; top failure reasons with artifact paths. Every local
report is labelled as not representative of the US-proxy test.

The corpora are `bench/corpora/mixed.txt` (15 queries, US/English) and
`bench/corpora/difficult.txt` (the difficult URL, byte-for-byte).

## Tests

```bash
.venv/bin/python -m pytest
```

95 tests, all offline (no browser, no Google): URL rules and pass-through
(including the difficult URL reaching the browser byte-for-byte), the
classifier (real CAPTCHA page + small `synthetic_*` pages), every parser against
16 real saved Google pages in `tests/fixtures/`, the API end to end with the
fetcher mocked, and the benchmark's maths and stop rules.

`scripts/capture_fixtures.py` lists which fixtures exist (default) or re-fetches
missing ones live (`--live`, paced, stops at a CAPTCHA). `scripts/demo_parse.py
<slug>` prints one fixture as the API's JSON, to compare with its screenshot.

## How parsing works

Google's class names are obfuscated and change. Hooks were chosen from ids,
`data-attrid`, `role`/`aria-*` attributes, visible heading text and structure
where possible, and every one was confirmed against the saved pages and
screenshots - not assumed. Where a class name was the only reliable hook it is
named in the parser's docstring so it's easy to update.

Google often renders a hidden accessibility copy right next to visible text; an
exact repeat of the line immediately before it is dropped. A section that fails
to parse logs a warning and leaves that field empty - the rest of the response
still returns.

**Organic** - each link containing an `<h3>` inside `#rso`, in page order. Its
result is the nearest ancestor with a `data-hveid` attribute. `title` is the
`<h3>`, `content` is the snippet, `sub_links` are real extra links in the result
(jump-to-section links, sitelink rows). The URL is the link's real destination:
used as-is when Google gives it directly, unwrapped from `/url?q=`, or - when
Google uses its opaque `/goto?url=<token>` wrapper - rebuilt from the visible
breadcrumb under the title (see [Known limitations](#known-limitations)).
Carousels, videos-only modules, People Also Ask, local packs, the flights module
and the forums module have no `<a><h3>` result in this sense and are not
included.

**Paid** - every `[data-text-ad]` inside `#tads` (top) and `#bottomads` (bottom),
in order, same shape as organic. The ad's own link is already the real
destination; ad sitelinks going through `/aclk?...&adurl=` use the `adurl`
value. Pages with no ads have empty `#tads`/`#bottomads`, so `paid: []` is
normal.

**AI Overview** - found from the heading whose text is exactly "AI Overview".
`ai_overview` is `null` only when the fully loaded page has none; if one is
present but unfinished the whole request is `aio_incomplete`. The content is read
top to bottom with these rules:

- **intro**: the paragraph blocks that come before the first section heading,
  one string per paragraph.
- **sections**: every heading at `aria-level="3"` starts a section; `title` is
  the heading text.
- **section text**: everything after that heading up to the next heading.
  Paragraphs are kept as lines. List items become lines starting with `"- "`.
  All lines are joined with `"\n"`. A bold label inside a list item stays part
  of that item (`"- HubSpot: Best for ..."`); it does not start a new section.
- The short closing paragraph Google often adds after the last section (e.g. "If
  you'd like, tell me ...") and any list under it stay in the last section, since
  no heading separates them.
- A list that appears before any heading is kept in `intro` as `"- "` lines.
- The small inline citation pills after sentences (favicon + "Publisher +1") are
  removed from the text; the sources they point to are listed in `sources`.
- Reading stops at the sources panel, so source cards never leak into the text.
- **sources**: every card in the sources panel (`li.h7wxwc`), including the ones
  only visible after "Show all" (the fetcher clicks "Show more" and "Show all"
  first). Each card gives `title`, `url` (the card link's real destination) and
  `snippet`. URLs are de-duplicated, `#:~:text=` fragments are stripped, and
  `google.com` links are dropped.

**Knowledge panel** - from `#rhs`: `title` and `subtitle` from the panel header,
`description` and `source_url` from the `description` block (the attribution
link, e.g. Wikipedia), and `facts` as label -> value for every `data-attrid="kc:/..."`
row that has a label (action buttons and edit links are skipped). No images. An
empty `#rhs` placeholder gives `null`.

**number_of_results** - the number in `#result-stats` ("About 129,000,000
results" -> `129000000`), `null` when Google doesn't show one.

**suggestions** - the query of each chip in the last "Related searches" / "People
also search for" block in `#botstuff`, taken from the chip's `q=` parameter (the
visible text often lacks a space between the bold part and the rest). The last
block is used because a knowledge panel can have its own earlier "People also
search for" carousel of related entities.

**corrections** - the corrected query from "Showing results for", "Search
instead for" or "Did you mean", else `[]`.

## Assumptions to confirm with the client

1. **`/goto` URLs.** When Google hides a result's destination behind its opaque
   `/goto?url=<token>` wrapper, we rebuild the URL from the visible breadcrumb
   (e.g. `https://en.wikipedia.org › wiki › Apple_Inc` -> `https://en.wikipedia.org/wiki/Apple_Inc`).
   That's real on-page text, but it can be only the site root when Google shows
   no breadcrumb. Acceptable, or should such results carry `url: null`?
2. **Partial pages.** With `results > 10`, if page 1 succeeds and page 2 is
   blocked, we return the error with `results: []` (per "results: [] on error"),
   discarding page 1. Alternative: return successful pages plus an error flag.
3. **"Can't generate an AI Overview right now"** is counted as `aio_incomplete`
   (a failure), not as `ai_overview: null`.
4. **Bold-labelled groups** inside AI Overview lists stay as `"- Label: text"`
   lines within their heading's section rather than becoming sections of their
   own; the closing paragraph stays in the last section.
5. **Malformed request bodies** return 400 with `error: "invalid_url"`, the
   closest code in the agreed list.
6. **Mid-page "in-feed" ads** (not in the top or bottom ad block) are not
   included in `paid`, which the brief defines as top and bottom ads.

## Known limitations

- **No live numbers yet.** From the development IP every automated request was
  CAPTCHA-blocked (2 of 2 attempts, ~18 h apart, 1 request each). Valid rate and
  latency are unmeasured.
- **Fetcher AI Overview logic untested live.** Detecting a loading AI Overview,
  waiting for it to settle and clicking "Show more"/"Show all" has only been
  tested with mocks. The hooks it uses (the "AI Overview" heading, `aria-busy`,
  text-length stability) are reasonable but unconfirmed on a live page.
- **`/goto`-wrapped AI Overview sources.** On 4 of the 11 fixtures with an AI
  Overview (apple, mobile, t_mobile, best_cell_phone_plans) Google wrapped every
  source card link in `/goto` and showed no URL text to fall back to. Those
  sources can't be recovered without reverse-engineering Google's script, so
  `sources` is empty on those pages even though cards are visible. Intro and
  sections are unaffected.
- **`/goto` organic URLs** can be less precise than the real destination (see
  assumption 1); sitelinks in Google's "site links" table layout have no link in
  the page at all, so their `sub_links` are empty.
- **Video results** in `organic` carry extra text in `content` (chapter
  timestamps, "key moments").
- **Knowledge panel** hooks are confirmed on only one fixture (Eiffel Tower); the
  other panels in the corpus were empty placeholders.
- **`corrections`** is unverified - no query in the corpus triggers it.
- **Fixtures were captured in a signed-in Chrome from an Indian IP** with
  `gl=us&hl=en`, so some pages show personalised results and local currency in
  ads. Page structure should match; exact results will differ from a clean
  US-proxy session.

## What's still needed to reach the targets (>= 98% valid, P95 <= 2 s per corpus)

1. **Run through the client's US residential proxies.** Set `PROXY_MODE` and
   run the benchmark (start small: `--limit 3`, then the full corpora). This is
   the first real measurement of block rate and latency.
2. **Confirm the AI Overview wait logic on live pages.** Check `X-AIO-State` and
   the saved screenshots for queries known to have an AI Overview; tune
   `AIO_APPEAR_WAIT_MS` / `AIO_MAX_WAIT_MS` and the loading signals.
3. **Expect P95 to be the hard target on AI Overview queries.** Google streams
   the AI Overview after the page loads, and a complete overview (plus "Show
   more"/"Show all") can take several seconds, which alone can exceed 2 s.
   Completeness is not traded for speed. Levers that don't sacrifice it: keep the
   browser warm (already done), `HEADLESS=true`, `BLOCK_RESOURCES=true`, detect
   "no AI Overview coming" earlier so plain queries return fast, and higher
   `CONCURRENCY` with one proxy per context for throughput.
4. **Measure the block rate per proxy.** If blocks are proxy-specific, use
   `PROXY_MODE=list` and `STOP_ON_BLOCK=false` for the run. Retrying a
   `blocked_captcha` on the same IP is deliberately not supported.
5. **Answer the assumptions above**, and re-check the parsers on a few live
   proxy pages (especially the `/goto` cases and knowledge panels).

## Project layout

```
app/
  main.py        FastAPI app: POST /serp, GET /health, debug headers
  config.py      settings from .env
  models.py      request/response models (client's exact schema)
  browser.py     Playwright lifecycle, page pool, resource blocking, proxy per context
  proxy.py       NoProxy / StaticProxy / ListProxy
  fetcher.py     navigate, classify early, wait for results + AI Overview, expand, capture, timings
  classify.py    CAPTCHA / consent / degraded / AI Overview state (pure functions)
  urls.py        URL validation, extra-page URLs, redirect unwrapping, fragment stripping
  parsers/       organic.py, ads.py, aio.py, knowledge_panel.py, misc.py
bench/
  run_bench.py   benchmark client
  corpora/       mixed.txt, difficult.txt
scripts/         capture_fixtures.py, save_fixture.py, stitch_screenshots.py, demo_parse.py, first_look.py
tests/           fixtures/ (16 real pages + screenshots, classifier pages) and test files
run.py           cross-platform launcher
artifacts/ reports/   git-ignored
```
