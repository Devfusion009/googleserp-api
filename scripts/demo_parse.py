"""Phase 3 demo: parse a saved fixture into the client's exact JSON shape.

Usage: python scripts/demo_parse.py <fixture_slug> [<fixture_slug> ...]
Not the real API (that's Phase 4) - just wires the parsers together so we can
eyeball the output next to each fixture's screenshot.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from selectolax.parser import HTMLParser  # noqa: E402

from app.classify import find_aio_root  # noqa: E402
from app.models import (  # noqa: E402
    AioSection,
    AioSource,
    AiOverview,
    OrganicItem,
    PageResult,
    SubLink,
)
from app.parsers.ads import parse_ads  # noqa: E402
from app.parsers.aio import parse_aio  # noqa: E402
from app.parsers.misc import parse_corrections, parse_number_of_results, parse_suggestions  # noqa: E402
from app.parsers.organic import parse_organic_results  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def parse_fixture(slug: str) -> tuple[PageResult, list[str]]:
    html = (FIXTURES / f"{slug}.html").read_text(encoding="utf-8")
    tree = HTMLParser(html)
    warnings: list[str] = []

    organic_raw, w = parse_organic_results(tree.css_first("#rso"))
    warnings += w
    organic = [OrganicItem(url=o.url, title=o.title, content=o.content, sub_links=[SubLink(title=s.title, url=s.url) for s in o.sub_links]) for o in organic_raw]

    paid_raw = parse_ads(tree.css_first("#tads"), warnings) + parse_ads(tree.css_first("#bottomads"), warnings)
    paid = [OrganicItem(url=a.url, title=a.title, content=a.content, sub_links=[SubLink(title=s.title, url=s.url) for s in a.sub_links]) for a in paid_raw]

    aio_root = find_aio_root(tree)
    ai_overview = None
    if aio_root is not None:
        parsed = parse_aio(aio_root)
        warnings += parsed.warnings
        if parsed.intro or parsed.sections or parsed.sources:
            ai_overview = AiOverview(
                intro=parsed.intro,
                sections=[AioSection(title=s.title, text=s.text) for s in parsed.sections],
                sources=[AioSource(title=s.title, url=s.url, snippet=s.snippet) for s in parsed.sources],
            )

    page = PageResult(
        page=1,
        paid=paid,
        organic=organic,
        ai_overview=ai_overview,
        knowledge_panel=None,  # not built yet - see PROGRESS.md
        number_of_results=parse_number_of_results(tree),
        suggestions=parse_suggestions(tree),
        corrections=parse_corrections(tree),
    )
    return page, warnings


if __name__ == "__main__":
    slugs = sys.argv[1:] or ["how_does_dns_work"]
    for slug in slugs:
        page, warnings = parse_fixture(slug)
        print(f"===== {slug} =====")
        print(json.dumps(page.model_dump(), indent=2, ensure_ascii=False))
        if warnings:
            print(f"--- {len(warnings)} parse warning(s) ---")
            for w in warnings:
                print(" -", w)
        print()
