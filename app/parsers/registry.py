"""Registry of page-block parsers.

Each entry is an adapter `(tree, ctx) -> dict` returning the PageResult
field(s) it fills (empty dict if the block is absent on the page). `ctx`
carries the resolved link map and collects warnings and gaps (parts of the page
that couldn't be extracted completely). Adding a new block type: write one
adapter below, append it to PAGE_PARSERS. Nothing else changes.
"""
from typing import Callable

from selectolax.parser import HTMLParser

from ..classify import find_aio_root
from ..models import AioSection, AioSource, AiOverview, KnowledgePanel, OrganicItem, SubLink
from .ads import parse_ads
from .aio import parse_aio
from .context import ParseContext
from .knowledge_panel import parse_knowledge_panel
from .misc import parse_corrections, parse_number_of_results, parse_suggestions
from .organic import parse_organic_results

BlockParser = Callable[[HTMLParser, ParseContext], dict]


def _organic(tree: HTMLParser, ctx: ParseContext) -> dict:
    raw, _ = parse_organic_results(tree.css_first("#rso") or tree, ctx)
    return {
        "organic": [
            OrganicItem(url=o.url, title=o.title, content=o.content, sub_links=[SubLink(title=s.title, url=s.url) for s in o.sub_links])
            for o in raw
        ]
    }


def _paid(tree: HTMLParser, ctx: ParseContext) -> dict:
    raw = parse_ads(tree.css_first("#tads"), ctx) + parse_ads(tree.css_first("#bottomads"), ctx)
    return {
        "paid": [
            OrganicItem(url=a.url, title=a.title, content=a.content, sub_links=[SubLink(title=s.title, url=s.url) for s in a.sub_links])
            for a in raw
        ]
    }


def _ai_overview(tree: HTMLParser, ctx: ParseContext) -> dict:
    root = find_aio_root(tree)
    if root is None:
        return {}
    parsed = parse_aio(root, ctx)
    if not (parsed.intro or parsed.sections or parsed.sources):
        return {}
    return {
        "ai_overview": AiOverview(
            intro=parsed.intro,
            sections=[AioSection(title=s.title, text=s.text) for s in parsed.sections],
            sources=[AioSource(title=s.title, url=s.url, snippet=s.snippet) for s in parsed.sources],
        )
    }


def _knowledge_panel(tree: HTMLParser, ctx: ParseContext) -> dict:
    kp = parse_knowledge_panel(tree)
    if kp is None:
        return {}
    return {"knowledge_panel": KnowledgePanel(title=kp.title, subtitle=kp.subtitle, description=kp.description, source_url=kp.source_url, facts=kp.facts)}


def _number_of_results(tree: HTMLParser, ctx: ParseContext) -> dict:
    return {"number_of_results": parse_number_of_results(tree)}


def _suggestions(tree: HTMLParser, ctx: ParseContext) -> dict:
    return {"suggestions": parse_suggestions(tree)}


def _corrections(tree: HTMLParser, ctx: ParseContext) -> dict:
    return {"corrections": parse_corrections(tree)}


PAGE_PARSERS: list[BlockParser] = [
    _organic,
    _paid,
    _ai_overview,
    _knowledge_panel,
    _number_of_results,
    _suggestions,
    _corrections,
]


def goto_tokens_needed(tree: HTMLParser, parsers: list[BlockParser] = PAGE_PARSERS) -> list[str]:
    """Every /goto token the parsers would put in the response, in page order.
    Runs them once with an empty link map; they record each token they ask for.
    Parsers may modify `tree`, so pass one that won't be parsed again."""
    ctx = ParseContext()
    for block_parser in parsers:
        block_parser(tree, ctx)
    return list(ctx.links.wanted)
