<p align="center">
  <img src="docs/media/banner.svg" alt="Google SERP API — real-browser Google results as structured JSON" width="100%">
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white">
  <img alt="Playwright" src="https://img.shields.io/badge/Playwright-1.47%2B-2EAD33?logo=playwright&logoColor=white">
  <img alt="Tests" src="https://img.shields.io/badge/tests-295%20passing-brightgreen">
  <img alt="Platforms" src="https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey">
</p>

**Google SERP API** is a self-hosted HTTP service that opens a Google results page in a real
browser and returns it as structured JSON:

- paid ads (top and bottom)
- organic results with sitelinks
- the **full AI Overview**: text, sections and every source, expanded
- the knowledge panel
- the result count, related searches and spelling corrections

It is built on FastAPI and Playwright. It uses no third-party SERP service, cache or other data
source. It never solves or bypasses CAPTCHAs, and it never invents data. A blocked, degraded or
incomplete page is reported as a failure with a precise error code. It is never passed off as a
result.

<p align="center">
  <img src="docs/media/hero.png" alt="A live Google page loaded through a Polish residential proxy, and the same page returned as JSON by POST /serp" width="100%">
</p>

---

## Contents

1. [Features](#features)
2. [How it works](#how-it-works)
3. [Requirements](#requirements)
4. [Quick start (5 minutes)](#quick-start-5-minutes)
5. [Step-by-step installation](#step-by-step-installation)
6. [Running in production with proxies](#running-in-production-with-proxies)
7. [API reference](#api-reference)
8. [Configuration reference](#configuration-reference)
9. [Benchmarking](#benchmarking)
10. [Testing](#testing)
11. [Performance results](#performance-results)
12. [Troubleshooting](#troubleshooting)
13. [Design rules and client decisions](#design-rules-and-client-decisions)
14. [Known limitations](#known-limitations)
15. [Project layout](#project-layout)

---

## Features

| | |
|---|---|
| **Exact client schema** | `POST /serp` returns `status_code`, `requests_used`, `elapsed_time`, `results[]`, `error` and `error_message`. These fields match the client's contract. |
| **Complete AI Overview** | Waits for Google to stream the overview, then clicks *Show more* / *Show all* and confirms each click worked. Returns every source with its real destination URL. |
| **Real destinations, never guesses** | Google `/goto` redirect links are resolved through Google's own redirect while the page is open. They are never rebuilt from the breadcrumb. |
| **Strict completeness gate** | If one result link or AI Overview source cannot be resolved, the page fails (`parse_error` / `aio_incomplete`). Partial data is never returned as valid. |
| **Honest classification** | CAPTCHA, consent wall, degraded page, timeout and network failure each have their own code and HTTP status. |
| **Residential proxy support** | Static or rotating proxies, sticky `{session}` ids, exit-IP checks, and a timezone that follows the exit IP. A local auth forwarder keeps Chrome's HTTP cache on. |
| **Human-like browsing** | Optional typed search, a warm-up before the first search, consent handling (*Reject all* / *Odrzuć wszystko* / *Alle ablehnen*), and locale and WebRTC settings that match the proxy country. |
| **Lean traffic** | Images, fonts and media are blocked inside Chrome through CDP, and the HTTP cache stays on. About **0.49 MB per page** through the proxy. |
| **Full observability** | Debug headers give per-stage timings, the Google request breakdown, the proxy session and exit IP, and the path to a saved HTML/screenshot artifact. |
| **Benchmark client included** | Calls the API like the client does. Reports valid rate, P50/P95 against the targets, traffic and failure reasons. |

---

## How it works

```mermaid
flowchart LR
    C([Client]) -->|POST /serp| API[FastAPI<br/>app/main.py]
    API --> ORC[Orchestrator<br/>pages · completeness gate · error codes]
    ORC --> F[Fetcher]
    F --> BM[Browser manager<br/>warm Chrome · one context per slot]
    BM --> FWD[Local proxy forwarder<br/>adds proxy login, keeps cache]
    FWD --> PX[(Residential proxy<br/>sticky session)]
    PX --> G[(Google)]
    F --> CL[Classifier<br/>CAPTCHA · consent · degraded · AIO state]
    F --> GR["/goto resolver<br/>in page via CDP"]
    F --> P[Parsers<br/>ads · organic · AI Overview · knowledge panel · misc]
    P --> ORC
    ORC -->|JSON + debug headers| C
```

One request, from start to finish:

```mermaid
sequenceDiagram
    autonumber
    participant Client
    participant API as SERP API
    participant Chrome as Chrome (warm context)
    participant Google
    Client->>API: POST /serp {url, results}
    API->>Chrome: open the search URL (or type the query in the search box)
    Chrome->>Google: GET /search via proxy
    Google-->>Chrome: results page
    API->>API: classify early (CAPTCHA? consent? degraded?)
    par AI Overview
        Chrome->>Google: /async follow-ups (overview streams in)
        API->>Chrome: click "Show more" / "Show all", confirm each click
    and Link prefetch
        Chrome->>Google: resolve /goto links already on the page
    end
    API->>API: capture DOM, parse, completeness gate
    API-->>Client: 200 JSON, or an error code with debug headers
```

The browser starts once and stays warm. Each slot keeps its own browser context and sticky proxy
session between requests. The second and later searches in a session therefore skip the homepage
and reuse cached scripts, which makes them several times faster than the first.

---

## Requirements

### System

| Requirement | Minimum | Recommended | Notes |
|---|---|---|---|
| OS | Linux, macOS 12+, Windows 10/11 | Ubuntu 22.04 / 24.04 LTS | Every platform is supported by `run.py`. |
| Python | **3.11** | 3.12 | Developed and tested on 3.12.3. |
| Browser | Playwright Chromium (bundled) | **Google Chrome stable** | Chrome (`BROWSER_CHANNEL=chrome`) is used for live runs. |
| Display | none, with `HEADLESS=true` | a desktop, or **Xvfb** on a server | Headful Chrome needs a display. On a server, use `xvfb-run`. |
| Disk | ~1 GB | 2 GB+ | Browser binaries plus debug artifacts (`artifacts/`, `reports/`). |
| Network | outbound HTTPS | low-latency route to the proxy gateway | Latency to the proxy dominates P95. An EU host is best for EU proxies. |

### Accounts and services

| Item | Needed for | Notes |
|---|---|---|
| **Residential proxy with sticky sessions** | any live traffic to Google | Without a proxy, a datacenter or office IP is usually CAPTCHA-blocked on the first request. Tested with Infatica residential (Poland and US). |
| Exit-IP lookup URL (optional) | timezone that follows the exit IP, IP-change detection | `https://ipinfo.io/json` works out of the box and must return JSON with a `timezone` field. |

### Python packages (`requirements.txt`)

| Package | Purpose |
|---|---|
| `fastapi`, `uvicorn[standard]` | HTTP API and ASGI server |
| `playwright` | browser automation, CDP access |
| `selectolax` (`<1.0`) | fast HTML parsing. 1.0 removed the Modest parser used here. |
| `pydantic`, `pydantic-settings` | request/response models, `.env` settings |
| `httpx` | benchmark client, `/goto` fallback, exit-IP checks |
| `pytest`, `pytest-asyncio` | test suite |

---

## Quick start (5 minutes)

<p align="center">
  <img src="docs/media/terminal-setup.png" alt="Install, start the server and run a health check" width="85%">
</p>

```bash
git clone <repository-url> googleserp_api && cd googleserp_api
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
cp .env.example .env
.venv/bin/python run.py
```

In a second terminal:

```bash
curl -s http://127.0.0.1:8000/health
# {"status":"ok"}
```

> [!IMPORTANT]
> The server is now running, but **live searches need a residential proxy.** Without one, Google
> almost always answers with a CAPTCHA, and the API correctly returns `429 blocked_captcha`. Set
> up a proxy as described in [Running in production with proxies](#running-in-production-with-proxies).

---

## Step-by-step installation

### Step 1: Get the code

```bash
git clone <repository-url> googleserp_api
cd googleserp_api
```

### Step 2: Check Python

```bash
python3 --version        # must print 3.11 or newer
```

On Ubuntu, if `venv` is missing: `sudo apt install python3-venv`.
On Windows, install Python from [python.org](https://www.python.org/downloads/) and tick
*Add python.exe to PATH*.

### Step 3: Create a virtual environment and install dependencies

<table>
<tr><th>Linux / macOS</th><th>Windows (PowerShell)</th></tr>
<tr><td>

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

</td><td>

```powershell
py -3.12 -m venv .venv
.venv\Scripts\pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt
```

</td></tr>
</table>

### Step 4: Install a browser

```bash
# Always: Playwright's Chromium and headless shell (also used by the browser tests)
.venv/bin/playwright install chromium

# Recommended for live runs: real Google Chrome
.venv/bin/playwright install chrome          # or install Chrome from google.com/chrome

# Linux only: system libraries the browser needs
sudo .venv/bin/playwright install-deps chromium
```

For headful Chrome on a Linux server with no desktop, install Xvfb as well:

```bash
sudo apt install -y xvfb
```

### Step 5: Configure

```bash
cp .env.example .env
```

Every setting has a working default. For a first local run, the defaults are enough. For live
traffic, see the [production profile](#production-profile-example-poland). Every variable is
documented in the [configuration reference](#configuration-reference).

> [!CAUTION]
> `.env` and proxy list files hold credentials. Both are git-ignored (`.env`, `proxies.txt`).
> Never commit them. On a shared machine, restrict them with `chmod 600`.

### Step 6: Run the test suite

```bash
.venv/bin/python -m pytest -q
```

<p align="center">
  <img src="docs/media/terminal-tests.png" alt="295 tests passing" width="85%">
</p>

All 295 tests run offline. None of them sends a request to Google. They take about 2 minutes,
most of it in the real-browser tests. See [Testing](#testing).

### Step 7: Start the API

<table>
<tr><th>Linux / macOS</th><th>Windows (PowerShell)</th></tr>
<tr><td>

```bash
.venv/bin/python run.py
```

</td><td>

```powershell
.venv\Scripts\python run.py
```

</td></tr>
</table>

`run.py` reads `HOST` and `PORT` from `.env` (default `127.0.0.1:8000`). On Windows, it selects
the Proactor event loop Playwright needs and never uses `--reload`. That combination is what
causes `NotImplementedError` when the browser launches. On Linux and macOS,
`uvicorn app.main:app` also works.

On a Linux server with headful Chrome:

```bash
xvfb-run -a --server-args="-screen 0 1920x1080x24" .venv/bin/python run.py
```

### Step 8: Open the interactive docs

Open <http://127.0.0.1:8000/docs> for the Swagger UI. Every endpoint can be tried from the
browser.

<p align="center">
  <img src="docs/media/swagger-ui.png" alt="Swagger UI for the SERP API" width="80%">
</p>

### Step 9: Make your first request

```bash
curl -s -X POST http://127.0.0.1:8000/serp \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.google.com/search?q=how%20does%20dns%20work&gl=us&hl=en","results":10}' | jq
```

PowerShell:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/serp -ContentType 'application/json' `
  -Body '{"url":"https://www.google.com/search?q=how%20does%20dns%20work&gl=us&hl=en","results":10}'
```

If `API_KEY` is set, add `-H 'X-API-Key: <key>'`. `/health` never needs a key.

---

## Running in production with proxies

### Proxy modes

| `PROXY_MODE` | Behaviour |
|---|---|
| `none` | Direct connection. Fine for development; expect CAPTCHAs on live searches. |
| `static` | One proxy URL template for every slot (`PROXY_URL`). |
| `list` | One proxy per line in `PROXY_LIST_FILE`, rotated per request. The browser context is rebuilt each time. |

Placeholders in `PROXY_URL` or in list lines:

- `{session}` is replaced with a fresh random id each time a browser context is built. Every
  context is then its own sticky session, for example
  `http://USER-session-{session}:PASS@host:port`. Use your provider's syntax.
- `{country}` is replaced with the request's `country` in lowercase, for providers that select
  the exit country through the username.

Credentials are masked in every log line (`http://use***@host:port`).

### Sticky sessions and IP changes

Everything for one page has to leave from **one IP**: the search, its scripts, the AI Overview
follow-ups and the `/goto` resolutions. That IP is the one Google set its cookies on.

- A context, and its proxy session, is replaced **only between requests**. It is replaced after a
  CAPTCHA or consent page, when it is older than `PROXY_SESSION_MAX_SECONDS`, after a browser or
  network error, or when the exit IP moved.
- With `EXIT_IP_CHECK_URL` set, the exit IP is checked through the slot's proxy.
  - **Changed while idle:** the slot starts a fresh session before the request.
  - **Changed during a request:** the change is recorded in `X-Proxy-Session`, and the next
    request gets a new session.

### Why the local proxy forwarder exists

When proxy credentials are given to Playwright, Playwright intercepts every request (CDP Fetch)
and **switches Chrome's HTTP cache off**. Every search then downloads Google's 1–2 MB of scripts
again. With `PROXY_LOCAL_FORWARDER=true` (the default), the service runs a tiny forwarder on
`127.0.0.1` instead. The forwarder adds the `Proxy-Authorization` header and relays HTTPS as an
opaque tunnel, so Chrome sees a proxy without a login and keeps its cache. This change alone took
traffic from 1.76 MB to 0.49 MB per page.

### Production profile (example: Poland)

This is the profile used for the latest measured run (see
[Performance results](#performance-results)). Adapt the locale, timezone and warm-up pages to the
proxy country.

```ini
# --- browser ---
HEADLESS=false                    # headful real Chrome; use xvfb-run on servers
BROWSER_CHANNEL=chrome
CONCURRENCY=1                     # one warm session per slot; scale with more slots/proxies
BLOCK_RESOURCES=true              # images/fonts/media blocked via CDP, cache kept

# --- proxy ---
PROXY_MODE=static
PROXY_URL=http://USER:PASS@gateway.example.com:10000
PROXY_LOCAL_FORWARDER=true        # keeps Chrome's HTTP cache on (default)
WEBRTC_PROXY_ONLY=true            # no UDP past the proxy (default)
PROXY_SESSION_MAX_SECONDS=0

# --- fingerprint matches the exit country ---
BROWSER_LOCALE=pl-PL
NATIVE_LOCALE=pl-PL
EXIT_IP_CHECK_URL=https://ipinfo.io/json
TIMEZONE_FROM_EXIT_IP=true        # Europe/Warsaw, taken from the exit IP
TIMEZONE_ID=Europe/Warsaw         # fallback if the check returns no timezone
EXIT_IP_CHECK_AFTER=false         # saves one proxy round trip per request

# --- human-like search ---
SEARCH_MODE=typed                 # homepage, then type the query
TYPED_ON_RESULTS_PAGE=true        # later searches type into the results page (fast path)
TYPED_WARMUP_MIN_MS=5000
TYPED_WARMUP_MAX_MS=15000
WARMUP_URLS=https://news.google.com/home?hl=pl&gl=PL&ceid=PL:pl,https://support.google.com/websearch/?hl=pl,https://pl.wikipedia.org/wiki/Wikipedia:Strona_g%C5%82%C3%B3wna

# --- timing and reliability ---
GOTO_PREFETCH=true                # resolve links while the AI Overview loads (default)
AIO_MAX_WAIT_MS=12000
REQUEST_DEADLINE_MS=45000
MAX_RETRIES=0                     # never retry a CAPTCHA
DEBUG_ARTIFACTS=true
DEBUG_SCREENSHOT_ON_SUCCESS=false
```

> [!TIP]
> **Keep sessions long and steady.** Google's risk scoring looks at session history. In the
> measured runs, later searches in a warm session had **zero CAPTCHAs (0 of 55)**. Bursts of new
> sessions, which look like one fingerprint on many IPs, were what got blocked. Leave 45–90 s
> between searches in a session, and pause for a few minutes after two blocked first searches in
> a row.

---

## API reference

### `GET /health`

Returns `{"status":"ok"}`. It never requires an API key. Use it for load-balancer and uptime
checks.

### `POST /serp`

**Request body**

| Field | Type | Default | Meaning |
|---|---|---|---|
| `url` | string | **required** | A Google search URL: `google.com` or `www.google.com`, path `/search`, with a `q=` parameter. It is sent to Google **exactly as given**. It is never re-encoded, reordered or "fixed". Anything else returns `400 invalid_url`, and nothing is fetched. |
| `results` | int | `10` | `10` returns page 1 only. Higher values fetch more pages by appending `&start=10`, `&start=20`, … to a copy of the URL. `num=` is never used. |
| `country` | string | `"US"` | Browser locale and `Accept-Language`, and the proxy country where the provider supports it. It never changes the URL. |
| `language` | string | `"en"` | As above. |
| `return_json` | bool | `true` | `false` returns page 1's rendered HTML as `text/html`. |

**Response body**

<p align="center">
  <img src="docs/media/terminal-response.png" alt="A real POST /serp response" width="70%">
</p>

Schema:

```jsonc
{
  "status_code": 200,
  "requests_used": 15,          // Google requests this call cost (page loads, /async, /goto)
  "elapsed_time": 3630,         // server-side milliseconds
  "results": [{
    "page": 1,
    "paid":    [ { "url": "...", "title": "...", "content": "...", "sub_links": [] } ],
    "organic": [ { "url": "...", "title": "...", "content": "...", "sub_links": [ { "title": "...", "url": "..." } ] } ],
    "ai_overview": {
      "intro":    ["..."],
      "sections": [ { "title": "...", "text": "..." } ],
      "sources":  [ { "title": "...", "url": "...", "snippet": "..." } ]
    },
    "knowledge_panel": { "title": "...", "subtitle": "...", "description": "...", "source_url": "...", "facts": {} },
    "number_of_results": 121,
    "suggestions": ["..."],
    "corrections": []
  }],
  "error": null,
  "error_message": null
}
```

**Status and error codes.** On any error, `results` is `[]`.

| HTTP | `error` | When |
|---|---|---|
| 200 | `null` | Valid, complete result. |
| 400 | `invalid_url` | URL not allowed, or malformed request body. |
| 401 | — | `API_KEY` is set and `X-API-Key` is missing or wrong. |
| 429 | `blocked_captcha` | Google CAPTCHA or "unusual traffic" (`/sorry/`). |
| 502 | `consent_wall` | "Before you continue" consent page. |
| 502 | `degraded_page` | JavaScript-required notice, basic-HTML version, no results container, or zero organic results. |
| 502 | `aio_incomplete` | The AI Overview did not finish loading or expanding in time, Google showed "can't generate an AI Overview right now", or a source card's destination could not be resolved. |
| 502 | `parse_error` | Parsing crashed, or a result's destination URL could not be resolved. |
| 502 | `network_error` | Browser or network failure, for example `ERR_TUNNEL_CONNECTION_FAILED`. |
| 504 | `timeout` | Navigation or the overall request deadline timed out. |

**What `requests_used` counts**

- Page loads, including every attempt and redirect hop.
- The page's `/async/` follow-ups. This is how the AI Overview arrives.
- `/goto` link resolutions.
- Not counted: requests served from Chrome's cache, and resources blocked before they leave the
  browser.
- Scripts, styles and logging pings to Google are not in `requests_used`. They are listed
  separately in `X-Google-Requests`.

**Debug headers.** These never appear in the JSON body.

| Header | Content |
|---|---|
| `X-Request-Id` | Unique id per request. Also in the logs. |
| `X-Classification` | `ok`, `blocked_captcha`, `aio_incomplete`, … |
| `X-AIO-State` | `absent` / `complete` / `incomplete` |
| `X-Timings` | JSON: `nav_ms`, `results_ms`, `aio_ms`, `links_ms`, `total_ms`, `attempt`, `links_needed` / `links_resolved` / `links_in_page`, `bytes_in`, `net_requests`, and partial-traffic markers. |
| `X-Google-Requests` | JSON: `requests_used`, plus every request by kind (`document`, `async`, `goto`, `goto_fallback`, `other_google`, `non_google`). |
| `X-Proxy-Session` | JSON: `session`, `exit_ip`, `exit_ip_after`, `ip_changed`. |
| `X-Artifact-Dir` | Saved HTML (and a screenshot on failure) for this request, when `DEBUG_ARTIFACTS=true`. |

---

## Configuration reference

All settings come from `.env` or from environment variables. Names are case-insensitive.
Environment variables take precedence over `.env`.

<details open>
<summary><b>Server and browser</b></summary>

| Variable | Default | Meaning |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Where `run.py` listens. Also the benchmark's default target. |
| `API_KEY` | empty | If set, `POST /serp` requires `X-API-Key: <value>`. |
| `HEADLESS` | `false` | `true` uses Playwright's headless shell, which needs no display. |
| `BROWSER_CHANNEL` | `chromium` | `chromium` (bundled) or `chrome` (installed Google Chrome). |
| `BROWSER_EXECUTABLE_PATH` | empty | Use a browser binary at this path. |
| `CONCURRENCY` | `1` | Browser slots used in parallel. Each slot has its own context and proxy session. |
| `PREWARM_SLOTS` | `true` | Build each slot (context, exit-IP check, warm-up) at startup. |
| `VIEWPORT_WIDTH` / `VIEWPORT_HEIGHT` | `1366` / `768` | Page viewport. |
| `SCREEN_WIDTH` / `SCREEN_HEIGHT` | `1920` / `1080` | Screen size the page reports. It is larger than the viewport, as on a real device. |
| `NATIVE_LOCALE` | `en-US` | Chrome's own language (`--lang`). Contexts in this locale use native values, not emulation. |
| `NATIVE_EN_US_LANGUAGES` | `true` | en-US contexts take their languages from Chrome itself. |
| `BROWSER_LOCALE` | empty | Force one browser locale for every request, for example `pl-PL`. Empty means it comes from the request. |
| `LAUNCH_PROXY` | `http://127.0.0.1:9` | Browser-wide proxy for Chrome's background services when a proxy is used. The default is a dead address, so background services fail instead of leaking from the host IP. |
| `WEBRTC_PROXY_ONLY` | `true` | WebRTC may not send UDP past the proxy. |

</details>

<details>
<summary><b>Traffic and resource blocking</b></summary>

| Variable | Default | Meaning |
|---|---|---|
| `BLOCK_RESOURCES` | `true` | Block images, fonts and media inside Chrome (CDP `Network.setBlockedURLs`). Scripts and stylesheets are never blocked, because the AI Overview needs them. |
| `BLOCKED_URL_PATTERNS` | images, fonts, media, Google image CDNs | Comma-separated Chrome wildcard patterns (`*` only; `?` is literal). |
| `PROXY_LOCAL_FORWARDER` | `true` | Local forwarder that adds the proxy login, so Chrome keeps its HTTP cache. |
| `TRAFFIC_BUDGET_MB` | `0` | Default for the benchmark's `--traffic-budget-mb`. `0` means no budget. |

</details>

<details>
<summary><b>Timing</b></summary>

| Variable | Default | Meaning |
|---|---|---|
| `NAV_TIMEOUT_MS` | `15000` | Navigation timeout, and the maximum wait for the results container. |
| `AIO_APPEAR_WAIT_MS` | `1500` | How long to wait for an AI Overview to appear once results are visible. |
| `AIO_MAX_WAIT_MS` | `12000` | Maximum time for an AI Overview to finish loading and expand, clicks included. After that, `aio_incomplete`. |
| `AIO_CLICK_TIMEOUT_MS` | `4000` | Per *Show more* / *Show all* click attempt. |
| `REQUEST_DEADLINE_MS` | `25000` | Hard cap per page load. After that, `timeout`. |
| `MAX_RETRIES` | `0` | Retries for `timeout` / `network_error` only. Never for a CAPTCHA. |
| `PROXY_UNREACHABLE_RETRIES` | `1` | Extra attempts, on the same session, when the proxy could not be reached at all (`net::ERR_TUNNEL_CONNECTION_FAILED` and similar: Google saw nothing). Only while the call is within `REQUEST_DEADLINE_MS`; the retry's requests, traffic and time count in the response. `0` turns it off. |
| `PROXY_UNREACHABLE_PAUSE_MS` | `[1000,2000]` | Random pause before that retry. |
| `GOTO_CONCURRENCY` | `16` | `/goto` links resolved in parallel per page. |
| `GOTO_TIMEOUT_MS` | `3000` | Timeout for one `/goto` resolution. |
| `GOTO_PREFETCH` | `true` | Resolve links already on the page while the AI Overview loads. |

</details>

<details>
<summary><b>Proxy and exit IP</b></summary>

| Variable | Default | Meaning |
|---|---|---|
| `PROXY_MODE` | `none` | `none`, `static` or `list`. |
| `PROXY_URL` | empty | For `static`: `http://user:pass@host:port`. Supports `{session}` and `{country}`. |
| `PROXY_LIST_FILE` | empty | For `list`: one proxy URL per line. |
| `PROXY_SESSION_MAX_SECONDS` | `0` | New session once the current one is this old. `0` means no age limit. |
| `EXIT_IP_CHECK_URL` | empty | URL that returns the caller's IP as JSON. It is requested through the slot's proxy. |
| `EXIT_IP_CHECK_TIMEOUT_MS` | `5000` | Timeout for that check. A failed check counts as "unknown", never as a change. |
| `EXIT_IP_RECHECK_SECONDS` | `60` | Skip the pre-request check if this slot was checked this recently. |
| `EXIT_IP_CHECK_AFTER` | `true` | Also check after each request, to record an IP change during it. |
| `TIMEZONE_FROM_EXIT_IP` | `true` | Browser timezone comes from the exit-IP check's `timezone` field. |
| `TIMEZONE_ID` | empty | IANA timezone fallback, for example `Europe/Warsaw`. |

</details>

<details>
<summary><b>Search behaviour and warm-up</b></summary>

| Variable | Default | Meaning |
|---|---|---|
| `SEARCH_MODE` | `url` | `url` opens the `/search` URL directly. `typed` opens the homepage and types the query with per-key delays. |
| `TYPED_KEY_DELAY_MIN_MS` / `MAX_MS` | `30` / `90` | Per-key typing delay. |
| `TYPED_WARMUP_MIN_MS` / `MAX_MS` | `0` / `0` | Random pause on the homepage before typing. |
| `TYPED_ON_RESULTS_PAGE` | `true` | Later searches in a session type into the results page's search box. |
| `WARMUP_URLS` | empty | Pages a new session visits before its first search. Comma-separated. |
| `WARMUP_DWELL_MIN_MS` / `MAX_MS` | `1000` / `3000` | Time spent on each warm-up page. |
| `REPO_FINGERPRINT` / `REPO_STATE_FILE` | `false` / empty | Experimental fingerprint patches and storage-state reuse. Off by default. |

</details>

<details>
<summary><b>Benchmark limits and debugging</b></summary>

| Variable | Default | Meaning |
|---|---|---|
| `MIN_DELAY_SECONDS` | `10` | Minimum gap between live requests in the benchmark and fixture tools. |
| `STOP_ON_BLOCK` | `true` | The benchmark stops at the first CAPTCHA. Set `false` only with a rotating proxy list. |
| `MAX_LIVE_REQUESTS_PER_RUN` | `30` | Larger runs need `--allow-more`. |
| `DEBUG_ARTIFACTS` | `true` | Save every page's HTML, plus a screenshot on failure, to `ARTIFACTS_DIR/<timestamp>_<query>/`. |
| `DEBUG_SCREENSHOT_ON_SUCCESS` | `false` | Also take a screenshot of successful pages. This costs time. |
| `ARTIFACTS_DIR` | `artifacts` | Where artifacts go. The directory is git-ignored. |

</details>

---

## Benchmarking

Start the API, then in a second terminal:

```bash
.venv/bin/python bench/run_bench.py --corpus mixed                  # 15 queries
.venv/bin/python bench/run_bench.py --corpus difficult --repeat 5   # the difficult URL, 5 times
.venv/bin/python bench/run_bench.py --corpus both --limit 3         # first 3 of each corpus
```

| Option | Default | Meaning |
|---|---|---|
| `--corpus` | `both` | `mixed`, `difficult` or `both` (`bench/corpora/*.txt`). |
| `--repeat N` | `1` | Repeat the corpus N times. |
| `--limit N` | all | Use only the first N URLs of each corpus. |
| `--concurrency N` | `1` | Parallel requests. |
| `--min-delay S` | `MIN_DELAY_SECONDS` | Gap between requests. |
| `--traffic-budget-mb MB` | `TRAFFIC_BUDGET_MB` | Stop before measured traffic would pass 70 % of this budget. |
| `--allow-more` | off | Allow more than `MAX_LIVE_REQUESTS_PER_RUN`. |
| `--base-url`, `--api-key`, `--timeout` | from `.env` | Target and credentials. |

Each run writes to `reports/<run_id>/`:

- `responses.jsonl`: every response.
- `report.md`, per corpus:
  - valid rate with counts per classification
  - P50 / P95 / max latency over **all** requests, with PASS/FAIL against ≥ 98 % and ≤ 2,000 ms
  - AI Overview statistics
  - stage timings
  - traffic per page and per run
  - Google requests by kind
  - proxy sessions and exit IPs
  - top failure reasons with artifact paths

A run that stops early still reports the request that stopped it and lists every query that was
**not executed**. Early stops happen at the first CAPTCHA, or before the traffic budget would be
passed.

---

## Testing

```bash
.venv/bin/python -m pytest -q                       # everything (~2 min)
.venv/bin/python -m pytest tests/test_pipeline.py   # one file
.venv/bin/python -m pytest -k proxy_forwarder       # by name
```

No test touches Google. The browser tests run a real Chromium against local servers that stand
in for Google and for an authenticating proxy.

| Test file | What it proves |
|---|---|
| `test_pipeline.py` | Classification and parsing end to end on 16 real saved Google pages: classifier, `/goto` tokens, parsers, completeness gate. |
| `test_parsers.py` | Every parser against the real pages: field values, no breadcrumb URLs, sitelinks, suggestions, knowledge panel, ads. |
| `test_links.py` | Link rules and the `/goto` resolver: in-page, fallback, `/sorry/`, no redirects followed, exact byte accounting. |
| `test_aio_expand.py`, `test_aio_people_also_ask.py` | AI Overview expansion. A click counts only when the page shows it worked. Failed clicks are retried. |
| `test_browser_local.py` | The production browser path in real Chromium: CDP blocking, cache kept, hidden templates ignored, `/goto` in page, link prefetch during the AIO wait, covered search box reached with `/`, consent handled during warm-up. |
| `test_browser_sessions.py` | Proxy sessions: fresh `{session}` per context, rotation by age and after a CAPTCHA, IP change while idle or during a request. |
| `test_proxy_forwarder.py` | The forwarder adds the proxy login to tunnels. With the forwarder Chrome keeps its cache; with the login given to Playwright the cache is off. |
| `test_block_patterns.py` | Blocked-URL patterns follow Chrome's wildcard semantics. |
| `test_netwatch.py`, `test_classify.py`, `test_urls.py`, `test_api.py`, `test_bench.py`, `test_fetcher_passthrough.py` | Traffic counting, classifier, URL rules (the difficult URL reaches the browser byte for byte), API envelope, benchmark maths and stop rules. |

To check one saved page by hand:

```bash
.venv/bin/python scripts/demo_parse.py how_does_dns_work    # classify + parse a fixture, print the JSON
.venv/bin/python scripts/capture_fixtures.py                # list fixtures (--live re-fetches missing ones, paced)
```

---

## Performance results

These are live measurements through **Polish residential proxies**: 60 searches in 5 sessions,
October 2026, with the [production profile](#production-profile-example-poland). The client's
targets are **≥ 98 % fully valid** and **P95 ≤ 2,000 ms**.

<p align="center">
  <img src="docs/media/progress.svg" alt="Validity, latency and traffic across the three Poland runs" width="100%">
</p>

| Metric (latest run) | Result | Target | |
|---|---|---|---|
| Pages served without CAPTCHA | **57 / 60 (95 %)** | | |
| Fully valid, of pages Google served | **56 / 57 (98 %)** | 98 % | ✅ met |
| Fully valid, of all searches | 56 / 60 (93 %) | 98 % | ⚠️ gap is first-search CAPTCHAs |
| Latency P50, valid pages | **3.9 s** | | 8× faster than the first run |
| Latency P95, valid pages | 13.3 s | 2.0 s | ❌ not met |
| Latency P50 / P95, later searches in a session | **3.9 s / 7.6 s** | | |
| Latency P50 / P95, first search of a session | 17.8 s / 22.4 s | | homepage, consent and warm-up |
| `requests_used` per valid page (avg / max) | 17 / 30 | | |
| Proxy traffic per valid page | **0.49 MB** | | down from 2.84 MB |

<p align="center">
  <img src="docs/media/stages.svg" alt="Per-stage latency breakdown" width="90%">
</p>

**Why P95 is above 2 s.**

1. A real browser waits for Google to generate the AI Overview, which takes about 1–3 s on
   Google's side. The service then expands it and resolves every source link.
2. Each page makes about 17 requests through a residential connection, and the round-trip time
   varies widely. "Reach results page" P95 alone is 10 s.
3. The first search of a session is deliberately slower (homepage, consent, warm-up), because
   skipping those steps causes CAPTCHAs.

**Next levers** (estimated to reach P50 ≈ 2–3 s and P95 ≈ 4–6 s):

- Host the service close to the proxy gateway, for example an EU VM for EU proxies.
- Keep pre-warmed sessions ready, so client requests rarely land on a first search.
- Hedged requests: re-issue a slow search on a second warm session and take the first answer.

Full run history and decisions: [`PROGRESS.md`](PROGRESS.md).

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Every request returns `429 blocked_captcha` | The IP is flagged. Use a residential proxy with sticky sessions (`PROXY_MODE`). Do not retry on the same IP. Use `SEARCH_MODE=typed` and `WARMUP_URLS` for new sessions. |
| `NotImplementedError` when the browser starts (Windows) | Start with `python run.py`, not `uvicorn --reload`. `run.py` sets the Proactor loop. |
| `Executable doesn't exist` / browser not found | Run `.venv/bin/playwright install chromium`, plus `install chrome` if `BROWSER_CHANNEL=chrome`. |
| `Missing X server or $DISPLAY` (Linux) | Use `HEADLESS=true`, or start with `xvfb-run -a .venv/bin/python run.py`. |
| Missing shared libraries (`libnss3`, `libatk`, …) | `sudo .venv/bin/playwright install-deps chromium` |
| Many `aio_incomplete` | Slow proxy route. Check `X-Timings.aio_ms`, consider raising `AIO_MAX_WAIT_MS`, and check the saved artifact in `X-Artifact-Dir`. |
| `network_error` with `ERR_TUNNEL_CONNECTION_FAILED` | The proxy or the local network dropped. Check the proxy gateway and credentials with `curl -x "$PROXY_URL" https://ipinfo.io/json`. |
| Traffic per page much higher than 0.5 MB | Check that `PROXY_LOCAL_FORWARDER=true` and `BLOCK_RESOURCES=true` are set. Credentials passed to Playwright directly turn the cache off. |
| Wrong timezone or language reported to Google | Set `EXIT_IP_CHECK_URL=https://ipinfo.io/json`, `TIMEZONE_FROM_EXIT_IP=true`, and `BROWSER_LOCALE` / `NATIVE_LOCALE` for the proxy country. |
| `401` on `/serp` | `API_KEY` is set. Send `X-API-Key`. |

Every request logs its id, the masked proxy, the URL sent, the final URL, the classification and
the timings. Match a log line to a response with `X-Request-Id`.

---

## Design rules and client decisions

**Rules**

- **Visible text only.** Google ships hidden templates next to real content, such as "Can't
  generate an AI overview right now" in `display:none`. The classifier and parsers skip anything
  the browser does not render.
- **Stable hooks.** Google's class names are obfuscated, so parsers rely on ids, `data-attrid`,
  `role` / `aria-*` attributes, heading text and structure. Each hook was confirmed against saved
  pages. Where a class name is the only hook, it is named in the parser's docstring.
- **Section failures are isolated.** A section that fails to parse logs a warning and leaves that
  field empty. Something visible that cannot be extracted completely fails the page instead.

**Confirmed by the client**

- Shopping and product cards that only open Google's product viewer are excluded from AI Overview
  `sources`.
- Google-hosted citations stay. Redirect wrappers are resolved. A citation that cannot be resolved
  makes the request incomplete; it is not dropped.
- `/goto` resolutions count in `requests_used`, together with retries and AI Overview follow-ups.

**Open assumptions** (defaults chosen, open to change)

1. Unresolved links use `parse_error` / `aio_incomplete`. A dedicated `incomplete_result` code
   can be added.
2. With `results > 10`, if any page fails, the whole request fails with `results: []`.
3. When Google visibly shows "Can't generate an AI Overview right now", the result is
   `aio_incomplete`, not `ai_overview: null`.
4. A malformed request body returns `400 invalid_url`.
5. Mid-page "in-feed" ads are not included in `paid`.

---

## Known limitations

- **P95 ≤ 2 s is not yet met.** See [Performance results](#performance-results) for the cause and
  the plan.
- **First searches can hit a CAPTCHA.** In the latest run, 2 of 5 new sessions were blocked on
  their first search. Later searches in a session had none.
- **Sitelinks in Google's table layout** are buttons with no link in the page, so their
  `sub_links` are empty.
- **Video results** carry extra text in `content` (chapters, "key moments").
- **Knowledge panel hooks** are confirmed on fewer pages than the other sections.
- **`corrections`** is not verified, because no query in the corpus triggers it.
- **Traffic accounting** comes from the browser's counter. It misses upload and TLS overhead, so
  the proxy provider's figure is higher. The benchmark applies a safety margin for this.

---

## Project layout

```text
app/
  main.py             FastAPI app: POST /serp, GET /health, debug headers
  config.py           every setting, loaded from .env
  models.py           request/response models (client's exact schema)
  orchestrator.py     one /serp request: pages, parsers, completeness gate, error codes
  browser.py          Chrome lifecycle, slots, contexts, proxy sessions, warm-up, launch flags
  proxy_forwarder.py  local forwarder that adds the proxy login (keeps the HTTP cache on)
  consent.py          Google consent dialog: "Reject all" in several languages
  fetcher.py          navigate or type, classify early, AI Overview wait/expand, capture, timings
  goto_resolver.py    resolve /goto links through Google's redirect (in page, then fallback)
  netwatch.py         CDP listener: bytes, cache hits, request kinds, blocked URLs, redirect Locations
  links.py            href to destination rules, /goto tokens, Location checks
  classify.py         CAPTCHA / consent / degraded / AI Overview state (visible text only)
  proxy.py            NoProxy / StaticProxy / ListProxy, {session} and {country}
  urls.py             URL validation, extra-page URLs, redirect unwrapping
  parsers/            organic, ads, aio, knowledge_panel, misc, context, registry
bench/
  run_bench.py        benchmark client
  corpora/            mixed.txt (15 queries), difficult.txt
scripts/              capture_fixtures, save_fixture, stitch_screenshots, demo_parse, first_look
tests/                295 tests; fixtures/ holds 16 real Google pages and screenshots
docs/media/           README images and charts
run.py                cross-platform launcher
.env.example          configuration template
artifacts/ reports/   runtime output (git-ignored)
```

---

<p align="center"><sub>Self-hosted · no third-party SERP data · no CAPTCHA solving · every failure reported honestly</sub></p>
