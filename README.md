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
| API (`POST /serp`, `GET /health`), exact response schema | Done |
| Classification + parsing on the 16 real saved Google pages | Done and tested together, end to end (`tests/test_pipeline.py`): all 16 classify `ok`, the 11 AI Overviews as complete. The 10 pages with direct links return a valid result offline; the 6 with `/goto` links fail honestly offline (their destinations need Google's redirect) and pass once the links are resolved. |
| `/goto` result links (organic, sitelinks, AI Overview sources, ads) | Resolved to the real destination through Google's own redirect while the page is open - never rebuilt from the breadcrumb. Verified with a real browser against a local stand-in for Google (`tests/test_browser_local.py`); **not yet run against live Google**. |
| Completeness | A result link without its destination, or an AI Overview source card without one, fails the page (`parse_error` / `aio_incomplete`) - partial extractions are never returned as valid. |
| Proxy support | Done - switch on with config only (see [Proxies](#proxies)) |
| Benchmark client | Done - see [Benchmark](#benchmark); now also reports traffic per page |
| **Live performance numbers** | **Not available yet.** The development machine's IP (India, no proxy) gets Google's "unusual traffic" CAPTCHA on the very first request, every time. The one local benchmark run stopped after 1 request (`blocked_captcha`). Valid-rate and latency against the client's targets can only be measured through the client's US residential proxies. |
| Live AI Overview wait/expand logic | Written, never exercised live (same reason). Parsers and classification are verified on saved pages; the in-browser waiting/clicking is not. |

"End to end" today means: a saved real Google page goes through the same
classifier, `/goto` token collection, parsers, completeness gate and error
mapping as a live request (fixtures), and the browser half - navigation,
resource blocking, hidden-element marking, in-page `/goto` resolution, traffic
counting - runs in a real Chromium against a local server. What has **not** run
against live Google: navigation through a proxy, the AI Overview wait/expand
clicks, and `/goto` resolution on Google's servers.

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
| 502 | `aio_incomplete` | an AI Overview is on the page but didn't finish loading/expanding in time, Google visibly shows its "can't generate an AI Overview right now" message, or a source card's destination couldn't be resolved / no source cards were found |
| 502 | `parse_error` | the page loaded but parsing crashed, or a result's destination URL couldn't be resolved (incomplete extraction) |
| 502 | `network_error` | browser/network failure |
| 504 | `timeout` | navigation or the overall request deadline timed out |

On any error `results` is `[]`. With `results > 10`, if any page fails the whole
request fails (see [Assumptions](#assumptions-to-confirm-with-the-client)).
`requests_used` counts the requests to Google the call cost, on every page:
page loads (every attempt and redirect hop, so retries count), the `/async/`
follow-ups the page makes (this is how the AI Overview arrives) and the `/goto`
link resolutions (4-18 per page on the saved pages). Requests are counted from
the browser's network events once they got an answer or failed on the network;
resources the blocker stopped never left the browser and aren't counted.
Scripts, styles and logging pings to Google hosts are not in `requests_used`
but are reported in `X-Google-Requests`.

**Debug headers** (never in the JSON body): `X-Request-Id`, `X-Classification`,
`X-AIO-State` (`absent` / `complete` / `incomplete`), `X-Timings` (JSON: `nav_ms`,
`results_ms`, `aio_ms`, `links_ms`, `total_ms`, `attempt`; `links_needed` /
`links_resolved` / `links_in_page` for `/goto` resolution; `bytes_in` and
`net_requests` - bytes received over the network and requests made for the
page), `X-Google-Requests` (JSON: `requests_used` and every request by kind -
`document`, `async`, `goto`, `goto_fallback`, `other_google`, `non_google`),
`X-Proxy-Session` (JSON: the proxy `session` id, `exit_ip` before and
`exit_ip_after` the request, `ip_changed`), `X-Artifact-Dir` (saved HTML +
screenshot for this request, when `DEBUG_ARTIFACTS=true`).

## Configuration

All settings come from `.env` (see `.env.example`) or environment variables.

| variable | default | meaning |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8000` | where `run.py` listens (also the benchmark's default target) |
| `API_KEY` | empty | if set, `POST /serp` requires `X-API-Key: <value>` |
| `HEADLESS` | `false` | `true` for servers without a display, and for proxy runs: it uses Playwright's headless shell, which makes no requests of its own. The full browser (`false`, or `BROWSER_CHANNEL=chrome`) contacts Google by itself (sign-in check, network time, `/async/folae`), one of them through the page's proxy. |
| `BROWSER_CHANNEL` | `chromium` | `chromium` (Playwright's bundled build) or `chrome` (installed Google Chrome). No stealth/fingerprint patches either way. |
| `BROWSER_EXECUTABLE_PATH` | empty | use a Chromium binary at this path instead of Playwright's own download |
| `CONCURRENCY` | `1` | number of browser pages kept open and used in parallel |
| `BLOCK_RESOURCES` | `true` | skip images, media and fonts (scripts and stylesheets are never blocked - the AI Overview needs them). Blocking uses request routing, which turns off the browser's HTTP cache: every page downloads Google's scripts again (see [Known limitations](#known-limitations)). |
| `NAV_TIMEOUT_MS` | `15000` | navigation timeout, and max wait for the results container |
| `AIO_APPEAR_WAIT_MS` | `1500` | how long to wait for an AI Overview to appear once results are visible |
| `AIO_MAX_WAIT_MS` | `8000` | max time for a present AI Overview to finish loading and expand; beyond this -> `aio_incomplete` |
| `REQUEST_DEADLINE_MS` | `25000` | hard cap per page load -> `timeout` |
| `MAX_RETRIES` | `0` | retries for `timeout` / `network_error` only - never for a CAPTCHA |
| `GOTO_CONCURRENCY` | `16` | `/goto` links resolved in parallel per page |
| `GOTO_TIMEOUT_MS` | `3000` | timeout for one `/goto` resolution; an unresolved link fails the page |
| `MIN_DELAY_SECONDS` | `10` | minimum gap between live requests in the benchmark and fixture tools |
| `STOP_ON_BLOCK` | `true` | benchmark and fixture capture stop at the first CAPTCHA (set `false` only with a rotating proxy list) |
| `MAX_LIVE_REQUESTS_PER_RUN` | `30` | the benchmark / fixture tools refuse bigger runs unless `--allow-more` |
| `PROXY_MODE` | `none` | `none`, `static` or `list` |
| `PROXY_URL` | empty | for `static`: `http://user:pass@host:port` |
| `PROXY_LIST_FILE` | empty | for `list`: file with one proxy URL per line, used round-robin |
| `PROXY_SESSION_MAX_SECONDS` | `0` | start a new proxy session (new browser context) before a request once the current one is this old; set it below the provider's shortest session lifetime. `0` = no age limit |
| `EXIT_IP_CHECK_URL` | empty | optional URL that answers with the caller's IP, requested through the slot's proxy before and after each request to detect exit-IP changes (a few hundred bytes each; not a Google request) |
| `EXIT_IP_CHECK_TIMEOUT_MS` | `5000` | timeout for that check; a failed check counts as "unknown", never as a change |
| `TRAFFIC_BUDGET_MB` | `0` | default for the benchmark's `--traffic-budget-mb` |
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

**Sticky sessions and IP changes.** Everything for one page - the search, its
scripts, the AI Overview's follow-up requests and the `/goto` resolutions -
should leave from one IP, the one Google set its cookies on. A request takes a
few seconds, so a session only has to hold for that long; how long it lasts
beyond that doesn't matter for correctness. A browser context is tied to one
proxy session and never carried to another:

- A literal `{session}` in `PROXY_URL` (or a list line) is replaced with a fresh
  random id every time a browser context is built, e.g.
  `http://USER-session-{session}:PASS@host:port` (use the provider's own
  session syntax). Every context is its own sticky session.
- The context - and so the session - is replaced only **between** requests,
  never during one: after a CAPTCHA or consent page, when it is older than
  `PROXY_SESSION_MAX_SECONDS`, after a browser/network error, or when the exit
  IP moved.
- With `EXIT_IP_CHECK_URL`, the exit IP is read through the slot's proxy before
  and after each request. Changed while idle: a fresh session before the
  request, so cookies never follow a new IP. Changed during a request: the
  request is kept and judged on what Google returned (a page broken by the
  switch fails like any other and is not retried); the change is recorded in
  `X-Proxy-Session` and the benchmark report, and the next request gets a fresh
  session.

`static` uses one session template for every slot; `list` rotates per request
and rebuilds the browser context each time.

## Benchmark

Start the API, then in a second terminal:

```bash
.venv/bin/python bench/run_bench.py --corpus mixed              # 15 queries
.venv/bin/python bench/run_bench.py --corpus difficult --repeat 5
.venv/bin/python bench/run_bench.py --corpus both --limit 3     # first 3 of each
```

Options: `--corpus mixed|difficult|both`, `--repeat N`, `--limit N`,
`--concurrency N` (default 1), `--min-delay S` (default `MIN_DELAY_SECONDS`),
`--traffic-budget-mb MB` (default `TRAFFIC_BUDGET_MB`), `--allow-more`,
`--base-url`, `--api-key`.

It calls the API over HTTP exactly like the client will and measures
client-side wall-clock time per request. Each run writes
`reports/<run_id>/responses.jsonl` (every response) and `report.md`, per corpus:
valid-result rate with counts per classification; P50 / P95 / max latency over
**all** requests including failures (nearest-rank), with PASS/FAIL against
>= 98% and <= 2000 ms; AI Overview appeared/complete/average sources per query;
average stage timings; traffic per page and for the run; Google requests
(`requests_used` total and every request by kind); proxy sessions, exit IPs
and requests with an IP change; top failure reasons with artifact paths. Runs
without a proxy are labelled as not representative of the US-proxy test.

A run that stops early - at the first CAPTCHA (`STOP_ON_BLOCK`) or before the
traffic budget would be passed - still reports the request that stopped it,
lists every query that was **not executed**, and says the figures don't
establish success rates. The budget check stops before one more page (the
largest measured so far) could take measured traffic past 70% of the budget:
the browser's counter misses upload and TLS overhead, so the proxy provider's
figure is higher.

The corpora are `bench/corpora/mixed.txt` (15 queries, US/English) and
`bench/corpora/difficult.txt` (the difficult URL, byte-for-byte).

## Tests

```bash
.venv/bin/python -m pytest
```

168 tests, none touching Google (2 of them need a local Chromium and are
skipped without one; point `BROWSER_EXECUTABLE_PATH` at a headless shell - the
full browser contacts Google by itself, see `HEADLESS`):

- `test_pipeline.py` - **classification and parsing together** on the 16 real
  saved pages: each goes through `classify_page`, the fetcher's `/goto` token
  collection, the parsers and the completeness gate, as a live request would.
  All 16 classify `ok` with the right AI Overview state (the hidden failure
  templates don't count; the same page with the template made visible is
  `aio_incomplete`); the 10 direct-link pages return a valid result; the 6
  `/goto` pages fail as incomplete with nothing resolved and pass once resolved;
  unresolved AI Overview sources alone give `aio_incomplete`.
- `test_parsers.py` - every parser against the real pages (field values, no
  breadcrumb URLs, sitelinks, suggestions, knowledge panel, ads).
- `test_links.py` - link rules and the `/goto` resolver (in-page, fallback,
  `/sorry/`, no redirects followed) with the browser faked.
- `test_browser_local.py` - the production browser path (BrowserManager +
  Fetcher + run_serp, resource blocking on) in a real Chromium against a local
  stand-in for Google: `/goto` links resolved in the page through CDP,
  stylesheet-hidden failure templates ignored, images blocked, bytes counted,
  `/goto` requests counted in `requests_used`, `/sorry/` -> `blocked_captcha`.
  Skipped if no Chromium can be launched.
- `test_browser_sessions.py` - proxy sessions with a fake browser: a fresh
  `{session}` id per context, rotation by age and after a CAPTCHA, an exit-IP
  change while idle (new session first) and during a request (recorded, new
  session next).
- URL rules and pass-through (the difficult URL reaches the browser
  byte-for-byte), the classifier on the real CAPTCHA page, the API with the
  fetcher mocked, and the benchmark's maths and stop rules.

`scripts/capture_fixtures.py` lists which fixtures exist (default) or re-fetches
missing ones live (`--live`, paced, stops at a CAPTCHA). `scripts/demo_parse.py
<slug>` runs one saved page through the classifier, parsers and completeness
check and prints the result, to compare with its screenshot.

## How parsing works

Google's class names are obfuscated and change. Hooks were chosen from ids,
`data-attrid`, `role`/`aria-*` attributes, visible heading text and structure
where possible, and every one was confirmed against the saved pages and
screenshots - not assumed. Where a class name was the only reliable hook it is
named in the parser's docstring so it's easy to update.

Google often renders a hidden accessibility copy right next to visible text; an
exact repeat of the line immediately before it is dropped. A section that fails
to parse logs a warning and leaves that field empty - the rest of the response
still returns. Something that is on the page but can't be extracted completely
(a result link with no known destination, an AI Overview source card without
one) is different: it fails the page - see [Completeness](#completeness).

**Classification only counts visible text.** Google ships hidden templates next
to real content - every AI Overview carries "An AI Overview is not available for
this search" and "Can't generate an AI overview right now" in `display:none`
spans, shown only when generation fails. Subtrees hidden by inline style, the
`hidden` attribute or (live) a stylesheet are skipped: before capturing the
page the fetcher stamps `data-serp-hidden` on elements inside the AI Overview
that the browser doesn't render, and the classifier skips those too.

**Result links and Google's `/goto` wrapper.** Since 26 Aug 2026 Google serves
signed-out result links as `/goto?url=<token>` (organic results, sitelinks, AI
Overview sources). The token is encrypted and different on every render, so it
can't be decoded, and the page itself carries at most the domain (the visible
breadcrumb is often just `https://site.com`, or category labels that aren't a
real path). The only reliable source is Google's own redirect: `GET
/goto?url=<token>` answers `302` with the destination in `Location`. After the
page has loaded (and the AI Overview is expanded), the fetcher:

1. runs the parsers once to learn exactly which `/goto` links the response will
   contain (not every `/goto` on the page),
2. requests those from inside the results page with `fetch(..., {redirect:
   'manual'})` - same HTTP/2 connection, cookies and proxy session as the page,
   redirect not followed, so the destination site is never contacted - and reads
   each `Location` through the Chrome DevTools Protocol,
3. retries anything missed through the browser context's own request client
   (same proxy, still no redirect followed),
4. hands the parsers the token -> destination map.

A `/sorry/` answer makes the page `blocked_captcha`. A link that still has no
destination is never replaced by a guess: its `url` stays `null` and the page
fails as incomplete. Links on Google's own hosts (e.g. `play.google.com`) are
not wrapped and are used as-is.

**Organic** - each link containing an `<h3>` inside `#rso`, in page order. Its
result is the nearest ancestor with a `data-hveid` attribute. `title` is the
`<h3>`, `content` is the snippet, `sub_links` are real extra links in the result
(jump-to-section links, sitelink rows, "More results from site"). The URL is the
link's real destination: used as-is when Google gives it directly, unwrapped from
`/url?q=`, or resolved from `/goto` as above. A Google-internal link (e.g. "More
results from www.reddit.com", `/search?q=...+site:...`) gets its absolute Google
URL, which is where it really goes. Carousels, videos-only modules, People Also
Ask, local packs, the flights module and the forums module have no `<a><h3>`
result in this sense and are not included.

**Paid** - every `[data-text-ad]` inside `#tads` (top) and `#bottomads` (bottom),
in order, same shape as organic. In the saved pages the ad's own link is already
the real destination; ad sitelinks going through `/aclk?...&adurl=` use the
`adurl` value, and a `/goto`-wrapped ad link would be resolved like organic
ones. Pages with no ads have empty `#tads`/`#bottomads`, so `paid: []` is
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
  first). Each card gives `title`, `url` (the card link's real destination,
  resolved from `/goto` or `/url?q=` when wrapped) and `snippet`. URLs are
  de-duplicated and `#:~:text=` fragments are stripped. A citation of a Google
  page (e.g. Google Flights) is a genuine source and is kept. Shopping cards -
  no link, `role="button"` and a product id (`data-cid`), opening Google's
  product viewer in the page - are UI rather than citations and are not listed.
  A citation whose destination can't be resolved is never dropped: the request
  becomes `aio_incomplete`, and so does an AI Overview with no source cards at
  all.

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

## Completeness

A response is valid only if everything the page shows in the fields we return
was extracted. Each parser records a *gap* when it sees something it can't
extract completely; any gap fails the page:

| gap | error |
|---|---|
| an organic result, sitelink or ad whose destination is unknown (e.g. a `/goto` link that didn't resolve) | `parse_error` - "incomplete extraction - N incomplete result links: ..." |
| an AI Overview citation whose destination is unknown, an AI Overview with no source cards, or AI Overview text that couldn't be read | `aio_incomplete` - "incomplete extraction - N incomplete AI Overview: ..." |

The message names the first few items. A page with zero organic results is
still `degraded_page` first.

## Decisions confirmed by the client

- Shopping/product cards that only open Google's product viewer are excluded
  from AI Overview `sources` (they are UI, not citations).
- Sources are not excluded for pointing at Google: redirect wrappers are
  resolved, genuine Google-hosted citations stay, and a citation that can't be
  resolved makes the request incomplete instead of being dropped.
- `/goto` link resolutions count in Google request usage (`requests_used`),
  with retries and AI Overview follow-ups.
- The first live run is a single-session smoke test that stops at the first
  CAPTCHA; its report includes that failure and the queries not executed, and
  it does not establish benchmark success rates.

## Assumptions to confirm with the client

1. **Unresolved links fail the page.** A result/sitelink/ad whose destination
   can't be resolved is reported as `parse_error` (and an AI Overview citation
   as `aio_incomplete`) - the closest codes in the agreed list. A dedicated code
   (e.g. `incomplete_result`) can be added if preferred. The breadcrumb is no
   longer used to rebuild URLs.
2. **What `requests_used` counts** - page loads (retries and redirect hops
   included), `/async/` follow-ups and `/goto` resolutions; not the page's
   scripts, styles and logging pings, which are listed separately in
   `X-Google-Requests`.
3. **Partial pages.** With `results > 10`, if page 1 succeeds and page 2 is
   blocked, we return the error with `results: []` (per "results: [] on error"),
   discarding page 1. Alternative: return successful pages plus an error flag.
4. **"Can't generate an AI Overview right now"**, when Google actually shows it,
   is counted as `aio_incomplete` (a failure), not as `ai_overview: null`.
5. **Bold-labelled groups** inside AI Overview lists stay as `"- Label: text"`
   lines within their heading's section rather than becoming sections of their
   own; the closing paragraph stays in the last section.
6. **Malformed request bodies** return 400 with `error: "invalid_url"`, the
   closest code in the agreed list.
7. **Mid-page "in-feed" ads** (not in the top or bottom ad block) are not
   included in `paid`, which the brief defines as top and bottom ads.

## Known limitations

- **No live numbers yet.** From the development IP every automated request was
  CAPTCHA-blocked (2 of 2 attempts, ~18 h apart, 1 request each). Valid rate and
  latency are unmeasured.
- **Fetcher AI Overview logic untested live.** Detecting a loading AI Overview,
  waiting for it to settle and clicking "Show more"/"Show all" has only been
  tested with mocks. The hooks it uses (the "AI Overview" heading, `aria-busy`,
  text-length stability) are reasonable but unconfirmed on a live page.
- **`/goto` resolution untested against live Google.** The mechanism (302 +
  `Location`, `GET` not `HEAD`, token not tied to cookies, no expiry within
  hours) follows public measurements from September 2026 and was verified in a
  real browser against a local server, not against Google. It adds one small
  request to `www.google.com` per `/goto` link in the response - 4 to 18 on the
  saved pages (out of 16-152 `/goto` links on those pages), run 16 at a time over
  the page's existing connection; whether that changes the block rate is one of
  the things the first proxy run measures (`X-Timings` `links_*`, report
  "Traffic" section).
- **Every page is a cold load while `BLOCK_RESOURCES=true`.** Blocking uses
  Playwright request routing, and routing turns off the browser's HTTP cache
  (verified: a script cacheable for a year was downloaded on each of 3 page
  loads with routing, once without). So each page downloads Google's scripts
  again. Blocking images and fonts in a way that keeps the cache (browser
  switches instead of routing) is the first traffic optimization to try once
  the smoke test has measured real page sizes.
- **The full browser contacts Google by itself.** Headed Chromium or Chrome
  (`HEADLESS=false`, `BROWSER_CHANNEL=chrome`) makes its own requests to Google
  (`accounts.google.com/ListAccounts`, `www.google.com/async/folae`, network
  time, device check-in, DNS-over-HTTPS) - one of them through the page's
  proxy, outside the page's request counters. Playwright's headless shell
  (`HEADLESS=true`) makes none; use it for proxy runs.
- **Saved `/goto` pages can't be fully checked offline.** 6 of the 16 fixtures
  (apple, best_cell_phone_plans, chase_bank_login, mobile, t_mobile, wikipedia)
  use `/goto`; their destinations were never captured, so offline they fail as
  incomplete and the tests check them with stand-in destinations.
- **Sitelinks in Google's "site links" table layout** have no link in the page
  at all (they are buttons), so their `sub_links` are empty.
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

1. **Single-session smoke test through the client's proxy** (100 MB allocated).
   It is the first real measurement of traffic per page, Google requests per
   page, `/goto` resolution on Google's servers and whether the page blocks;
   it does not establish success rates.

   ```ini
   HEADLESS=true                      # headless shell: no requests of its own
   CONCURRENCY=1
   PROXY_MODE=static
   PROXY_URL=http://USER-session-{session}:PASS@HOST:PORT   # provider's session syntax
   PROXY_SESSION_MAX_SECONDS=...      # below the shortest session lifetime they give
   EXIT_IP_CHECK_URL=...              # if the provider offers one through the proxy
   TRAFFIC_BUDGET_MB=100
   STOP_ON_BLOCK=true
   ```

   ```bash
   .venv/bin/python bench/run_bench.py --corpus mixed --limit 3   # 3 requests; check the report
   .venv/bin/python bench/run_bench.py --corpus both --repeat 1   # 15 mixed + 1 difficult
   .venv/bin/python bench/run_bench.py --corpus difficult --repeat 4
   ```

   At most 23 page loads, 10 s apart. Every report lists what didn't run and
   why (first CAPTCHA, or the traffic budget).
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
  orchestrator.py  one /serp request: pages, parsers, completeness gate, error codes
  browser.py     Playwright lifecycle, page pool, resource blocking, proxy per context
  netwatch.py    CDP listener per page: bytes received, /goto redirect Locations
  proxy.py       NoProxy / StaticProxy / ListProxy
  fetcher.py     navigate, classify early, wait for results + AI Overview, expand, capture, resolve /goto, timings
  goto_resolver.py  resolve /goto links through Google's redirect (in page, then fallback)
  links.py       href -> destination rules, /goto tokens, Location checks
  classify.py    CAPTCHA / consent / degraded / AI Overview state, visible text only (pure functions)
  urls.py        URL validation, extra-page URLs, redirect unwrapping, fragment stripping
  parsers/       organic.py, ads.py, aio.py, knowledge_panel.py, misc.py, context.py (links, warnings, gaps), registry.py
bench/
  run_bench.py   benchmark client
  corpora/       mixed.txt, difficult.txt
scripts/         capture_fixtures.py, save_fixture.py, stitch_screenshots.py, demo_parse.py, first_look.py
tests/           fixtures/ (16 real pages + screenshots, classifier pages) and test files
run.py           cross-platform launcher
artifacts/ reports/   git-ignored
```
