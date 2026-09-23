"""Fixture pages for parser tests: tests/fixtures/<slug>.html + <slug>.png.

Two ways to get them:
  --check     (default) list which fixtures exist / are missing, and print the
              exact URL to open in your normal Chrome for each missing one.
  --live      fetch missing ones with the real fetcher, paced, stop at first CAPTCHA.
              Asks for --allow-more above MAX_LIVE_REQUESTS_PER_RUN.

Manual pages (option 3): open the URL in normal Chrome (incognito, not logged in),
click 'Show more' in the AI Overview and 'Show all' on its sources, then
DevTools > Elements > right-click <html> > Copy > Copy outerHTML, save as
tests/fixtures/<slug>.html; full-page screenshot as tests/fixtures/<slug>.png
(DevTools > Ctrl+Shift+P > 'Capture full size screenshot').
"""
import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "tests" / "fixtures"
CORPORA = ROOT / "bench" / "corpora"


def slug_for(url: str) -> str:
    q = unquote(re.search(r"[?&]q=([^&#]*)", url).group(1))
    s = re.sub(r"[^a-z0-9]+", "_", q.lower()).strip("_")
    return ("difficult_" + s) if "hl=us" in url else s


def corpus_urls() -> list[str]:
    urls = []
    for name in ("mixed.txt", "difficult.txt"):
        urls += [l.strip() for l in (CORPORA / name).read_text().splitlines() if l.strip()]
    return urls


def write_manifest() -> dict:
    manifest_path = FIXTURES / "manifest.json"
    old = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest = {}
    for url in corpus_urls():
        slug = slug_for(url)
        entry = old.get(slug, {})
        entry["url"] = url
        entry["html"] = (FIXTURES / f"{slug}.html").exists()
        entry["screenshot"] = (FIXTURES / f"{slug}.png").exists()
        entry.setdefault("source", None)  # "manual_chrome" or "live"
        manifest[slug] = entry
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def check() -> None:
    manifest = write_manifest()
    missing = [s for s, e in manifest.items() if not (e["html"] and e["screenshot"])]
    for slug, e in manifest.items():
        mark = "OK " if slug not in missing else "-- "
        print(f"{mark} {slug:60s} html={e['html']!s:5} png={e['screenshot']!s:5} source={e['source']}")
    print(f"\n{len(manifest) - len(missing)}/{len(manifest)} complete.")
    if missing:
        print("\nOpen these in normal Chrome and save as tests/fixtures/<slug>.html / .png:")
        for slug in missing:
            print(f"  {slug}.html  <-  {manifest[slug]['url']}")


async def live(limit: int, allow_more: bool) -> None:
    from app.browser import BrowserManager
    from app.classify import Classification
    from app.config import get_settings
    from app.fetcher import Fetcher

    s = get_settings()
    manifest = write_manifest()
    todo = [(slug, e["url"]) for slug, e in manifest.items() if not e["html"]][:limit]
    if len(todo) > s.max_live_requests_per_run and not allow_more:
        sys.exit(f"{len(todo)} live requests > MAX_LIVE_REQUESTS_PER_RUN={s.max_live_requests_per_run}; pass --allow-more")
    bm = BrowserManager(s)
    await bm.start()
    fetcher = Fetcher(s, bm)
    try:
        for n, (slug, url) in enumerate(todo):
            if n:
                time.sleep(s.min_delay_seconds)
            r = await fetcher.fetch(url, "US", "en")
            print(f"{slug}: {r.classification.value} ({r.reason}) aio={r.aio_state.value} artifacts={r.artifact_dir}")
            if r.classification is Classification.blocked_captcha:
                print("CAPTCHA - stopping. Wait before trying again.")
                break
            if r.classification is Classification.ok and r.artifact_dir:
                (FIXTURES / f"{slug}.html").write_text(r.html, encoding="utf-8")
                png = Path(r.artifact_dir) / "screenshot.png"
                if png.exists():
                    (FIXTURES / f"{slug}.png").write_bytes(png.read_bytes())
                manifest[slug]["source"] = "live"
                (FIXTURES / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    finally:
        await bm.stop()
        write_manifest()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--limit", type=int, default=16)
    ap.add_argument("--allow-more", action="store_true")
    a = ap.parse_args()
    asyncio.run(live(a.limit, a.allow_more)) if a.live else check()
