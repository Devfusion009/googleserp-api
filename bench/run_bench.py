"""Benchmark the running API over HTTP, the way the client will.

Usage:
  python bench/run_bench.py --corpus both --repeat 1
  python bench/run_bench.py --corpus difficult --repeat 5
  python bench/run_bench.py --corpus mixed --limit 3

Every request is a live Google page load through the API, so this refuses to
plan more than MAX_LIVE_REQUESTS_PER_RUN calls unless --allow-more is passed,
waits --min-delay seconds between calls, and stops at the first blocked_captcha.

Latency is client-side wall-clock time per HTTP call, over ALL requests
(failures included), percentiles by the nearest-rank method.
"""
import argparse
import asyncio
import json
import math
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402

CORPORA = ROOT / "bench" / "corpora"
REPORTS = ROOT / "reports"

TARGET_VALID_RATE = 0.98
TARGET_P95_MS = 2000
LOCAL_LABEL = (
    "Local run from India without proxies. Latency and block rate are NOT "
    "representative of the client's US-proxy test."
)
STAGES = ("nav_ms", "results_ms", "aio_ms", "total_ms")


@dataclass
class Call:
    corpus: str
    url: str
    status: int | None
    classification: str
    wall_ms: int
    aio_state: str | None
    aio_sources: int | None
    timings: dict = field(default_factory=dict)
    error_message: str | None = None
    artifact_dir: str | None = None


def load_corpus(name: str) -> list[str]:
    return [l.strip() for l in (CORPORA / f"{name}.txt").read_text().splitlines() if l.strip()]


def nearest_rank(values: list[int], p: float) -> int | None:
    """Nearest-rank percentile: the smallest value with at least p% of values <= it."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


def plan(corpus: str, repeat: int, limit: int | None) -> list[tuple[str, str]]:
    names = ["mixed", "difficult"] if corpus == "both" else [corpus]
    jobs: list[tuple[str, str]] = []
    for name in names:
        urls = load_corpus(name)
        if limit:
            urls = urls[:limit]
        jobs += [(name, u) for _ in range(repeat) for u in urls]
    return jobs


async def call_api(client: httpx.AsyncClient, base_url: str, api_key: str | None, corpus: str, url: str) -> tuple[Call, dict | None]:
    body = {"url": url, "results": 10, "country": "US", "language": "en", "return_json": True}
    headers = {"X-API-Key": api_key} if api_key else {}
    t0 = time.perf_counter()
    try:
        resp = await client.post(f"{base_url}/serp", json=body, headers=headers)
    except httpx.HTTPError as e:
        wall = int((time.perf_counter() - t0) * 1000)
        return Call(corpus, url, None, "client_error", wall, None, None, error_message=f"{type(e).__name__}: {e}"), None
    wall = int((time.perf_counter() - t0) * 1000)
    try:
        data = resp.json()
    except ValueError:
        data = None
    classification = resp.headers.get("X-Classification") or ("ok" if resp.status_code == 200 else "unknown")
    try:
        timings = json.loads(resp.headers.get("X-Timings") or "{}")
    except ValueError:
        timings = {}
    sources = None
    if data and data.get("results"):
        aio = data["results"][0].get("ai_overview")
        sources = len(aio["sources"]) if aio else 0
    return (
        Call(
            corpus=corpus,
            url=url,
            status=resp.status_code,
            classification=classification,
            wall_ms=wall,
            aio_state=resp.headers.get("X-AIO-State"),
            aio_sources=sources,
            timings=timings,
            error_message=(data or {}).get("error_message"),
            artifact_dir=resp.headers.get("X-Artifact-Dir"),
        ),
        data,
    )


def summarize(calls: list[Call]) -> dict:
    n = len(calls)
    valid = sum(1 for c in calls if c.classification == "ok")
    walls = [c.wall_ms for c in calls]
    p95 = nearest_rank(walls, 95)
    rate = valid / n if n else 0.0

    per_query: dict[str, dict] = defaultdict(lambda: {"runs": 0, "appeared": 0, "complete": 0, "sources": []})
    for c in calls:
        q = per_query[c.url]
        q["runs"] += 1
        if c.aio_state in ("complete", "incomplete"):
            q["appeared"] += 1
        if c.aio_state == "complete" and c.classification == "ok":
            q["complete"] += 1
            if c.aio_sources is not None:
                q["sources"].append(c.aio_sources)

    stage_avgs = {}
    for stage in STAGES:
        vals = [c.timings[stage] for c in calls if isinstance(c.timings.get(stage), (int, float))]
        stage_avgs[stage] = round(sum(vals) / len(vals)) if vals else None

    failures = Counter((c.classification, c.error_message or "") for c in calls if c.classification != "ok")
    failure_artifacts = defaultdict(list)
    for c in calls:
        if c.classification != "ok" and c.artifact_dir:
            failure_artifacts[(c.classification, c.error_message or "")].append(c.artifact_dir)

    return {
        "n": n,
        "valid": valid,
        "valid_rate": rate,
        "valid_pass": rate >= TARGET_VALID_RATE,
        "by_classification": dict(Counter(c.classification for c in calls)),
        "p50": nearest_rank(walls, 50),
        "p95": p95,
        "max": max(walls) if walls else None,
        "p95_pass": p95 is not None and p95 <= TARGET_P95_MS,
        "per_query": per_query,
        "stage_avgs": stage_avgs,
        "failures": failures.most_common(),
        "failure_artifacts": failure_artifacts,
    }


def render_report(run_id: str, args: argparse.Namespace, by_corpus: dict[str, dict], stopped_reason: str | None) -> str:
    lines = [f"# Benchmark report `{run_id}`", "", f"> **{LOCAL_LABEL}**", ""]
    lines += [
        f"- Corpus: `{args.corpus}`, repeat {args.repeat}, limit {args.limit or '-'}, concurrency {args.concurrency}, min delay {args.min_delay}s",
        f"- Targets (per corpus): valid >= {TARGET_VALID_RATE:.0%}, P95 <= {TARGET_P95_MS} ms",
    ]
    if stopped_reason:
        lines += ["", f"**Run stopped early:** {stopped_reason}"]
    for name, s in by_corpus.items():
        pf = lambda ok: "PASS" if ok else "FAIL"  # noqa: E731
        lines += ["", f"## Corpus: {name}", ""]
        lines += [
            f"- Valid results: **{s['valid']}/{s['n']} ({s['valid_rate']:.1%})** - {pf(s['valid_pass'])}",
            f"- By classification: {', '.join(f'{k}={v}' for k, v in sorted(s['by_classification'].items()))}",
            f"- Latency (all requests, nearest-rank): P50 {s['p50']} ms, **P95 {s['p95']} ms** - {pf(s['p95_pass'])}, max {s['max']} ms",
            *(
                [f"- _Caution: only {s['valid']} of {s['n']} requests returned a valid result. The latency figures include fast "
                 "failures (e.g. an instant CAPTCHA redirect), so a latency PASS here says nothing about real page load time._"]
                if not s["valid_pass"] else []
            ),
            "",
            "### Where the time goes (server-side stage averages, ms since request start)",
            "",
            "| stage | avg ms |",
            "|---|---|",
        ]
        lines += [f"| {k} | {v if v is not None else '-'} |" for k, v in s["stage_avgs"].items()]
        lines += ["", "### AI Overview per query", "", "| query URL | runs | appeared | complete | avg sources |", "|---|---|---|---|---|"]
        for url, q in s["per_query"].items():
            avg = f"{sum(q['sources']) / len(q['sources']):.1f}" if q["sources"] else "-"
            lines.append(f"| `{url}` | {q['runs']} | {q['appeared']} | {q['complete']} | {avg} |")
        lines += ["", "### Top failure reasons", ""]
        if not s["failures"]:
            lines.append("None.")
        for (cls, msg), count in s["failures"]:
            arts = s["failure_artifacts"].get((cls, msg), [])
            lines.append(f"- **{cls}** x{count}: {msg or '(no message)'}")
            for a in arts[:3]:
                lines.append(f"  - artifact: `{a}`")
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    jobs = plan(args.corpus, args.repeat, args.limit)
    cap = settings.max_live_requests_per_run
    print(f"Planned {len(jobs)} live request(s) (cap {cap}).")
    if len(jobs) > cap and not args.allow_more:
        print(f"Refusing: {len(jobs)} > MAX_LIVE_REQUESTS_PER_RUN={cap}. Pass --allow-more to override.")
        return 2
    if not jobs:
        print("Nothing to run.")
        return 0

    run_id = time.strftime("%Y%m%d_%H%M%S")
    out_dir = REPORTS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    responses_path = out_dir / "responses.jsonl"

    calls: list[Call] = []
    stopped_reason: str | None = None
    stop = asyncio.Event()
    sem = asyncio.Semaphore(max(1, args.concurrency))
    start_lock = asyncio.Lock()
    last_start = [0.0]

    async with httpx.AsyncClient(timeout=args.timeout) as client:

        async def one(i: int, corpus: str, url: str) -> None:
            nonlocal stopped_reason
            async with sem:
                async with start_lock:  # keep >= min-delay between live requests
                    if stop.is_set():
                        return
                    wait = last_start[0] + args.min_delay - time.monotonic()
                    if last_start[0] and wait > 0:
                        await asyncio.sleep(wait)
                    if stop.is_set():
                        return
                    last_start[0] = time.monotonic()
                call, data = await call_api(client, args.base_url, args.api_key, corpus, url)
                # measure the next gap from when this one *finished* too, so a
                # slow request doesn't eat into the idle time before the next
                last_start[0] = time.monotonic()
                calls.append(call)
                with responses_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"corpus": corpus, "url": url, "status": call.status, "wall_ms": call.wall_ms,
                                        "classification": call.classification, "headers_timings": call.timings,
                                        "artifact_dir": call.artifact_dir, "response": data}) + "\n")
                print(f"[{len(calls)}/{len(jobs)}] {corpus:9s} {call.classification:16s} {call.wall_ms:6d} ms  aio={call.aio_state}  {url}")
                if call.classification == "blocked_captcha" and not stop.is_set():
                    stopped_reason = "Google returned a CAPTCHA (blocked_captcha). Wait at least an hour before trying again from this IP."
                    stop.set()

        await asyncio.gather(*(one(i, c, u) for i, (c, u) in enumerate(jobs)))

    by_corpus = {}
    for name in ("mixed", "difficult"):
        subset = [c for c in calls if c.corpus == name]
        if subset:
            by_corpus[name] = summarize(subset)

    report = render_report(run_id, args, by_corpus, stopped_reason)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    print()
    print(report)
    print(f"Saved: {out_dir / 'report.md'} and {responses_path}")
    if stopped_reason:
        print(f"\n*** {stopped_reason} ***")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    s = get_settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", choices=["mixed", "difficult", "both"], default="both")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None, help="use only the first N URLs of each corpus")
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--min-delay", type=float, default=s.min_delay_seconds)
    ap.add_argument("--allow-more", action="store_true")
    ap.add_argument("--base-url", default=f"http://{s.host}:{s.port}")
    ap.add_argument("--api-key", default=s.api_key or None)
    ap.add_argument("--timeout", type=float, default=60.0, help="per-request HTTP timeout, seconds")
    return ap.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(run(parse_args())))
