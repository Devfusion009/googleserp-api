"""Parse a saved fixture the way the API does and print the result.

Usage: python scripts/demo_parse.py <fixture_slug> [<fixture_slug> ...]

Runs the same classifier, parsers and completeness check as a live request,
minus the browser. Saved pages can't have their /goto links resolved (that
needs Google's redirect, live), so pages with /goto links show as incomplete
here - the gap list says which links.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from selectolax.parser import HTMLParser  # noqa: E402

from app.classify import classify_page  # noqa: E402
from app.orchestrator import build_page_result, completeness_error  # noqa: E402
from app.parsers.context import ParseContext  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def main(slug: str) -> None:
    html = (FIXTURES / f"{slug}.html").read_text(encoding="utf-8")
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    url = manifest.get(slug, {}).get("url", "https://www.google.com/search?q=x")
    verdict = classify_page(url, html)
    ctx = ParseContext()
    page = build_page_result(1, HTMLParser(html), ctx)
    incomplete = completeness_error(ctx.gaps)
    print(f"===== {slug} =====")
    print(f"classification: {verdict.classification.value} ({verdict.reason}); aio: {verdict.aio_state.value}")
    print(f"completeness: {'complete' if incomplete is None else incomplete[0] + ' - ' + incomplete[1]}")
    print(json.dumps(page.model_dump(), indent=2, ensure_ascii=False))
    if ctx.warnings:
        print(f"--- {len(ctx.warnings)} parse warning(s) ---")
        for w in ctx.warnings:
            print(" -", w)
    print()


if __name__ == "__main__":
    for slug in sys.argv[1:] or ["how_does_dns_work"]:
        main(slug)
