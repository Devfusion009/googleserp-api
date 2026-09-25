"""Registry of page-block parsers.

Each entry is an adapter `(tree, warnings) -> dict` returning the PageResult
field(s) it fills (empty dict if the block is absent on the page). Adding a
new block type: write one adapter below, append it to PAGE_PARSERS. Nothing
else changes.
"""
from typing import Callable

from selectolax.parser import HTMLParser

from ..classify import find_aio_root
from ..models import AioSection, AioSource, AiOverview, KnowledgePanel, OrganicItem, SubLink
from .ads import parse_ads
from .aio import parse_aio
from .knowledge_panel import parse_knowledge_panel
from .misc import parse_corrections, parse_number_of_results, parse_suggestions
from .organic import parse_organic_results

BlockParser = Callable[[HTMLParser, list[str]], dict]


def _organic(tree: HTMLParser, warnings: list[str]) -> dict:
    raw, w = parse_organic_results(tree.css_first("#rso") or tree)
    warnings.extend(w)
    return {
        "organic": [
            OrganicItem(url=o.url, title=o.title, content=o.content, sub_links=[SubLink(title=s.title, url=s.url) for s in o.sub_links])
            for o in raw
        ]
    }


def _paid(tree: HTMLParser, warnings: list[str]) -> dict:
    raw = parse_ads(tree.css_first("#tads"), warnings) + parse_ads(tree.css_first("#bottomads"), warnings)
    return {
        "paid": [
            OrganicItem(url=a.url, title=a.title, content=a.content, sub_links=[SubLink(title=s.title, url=s.url) for s in a.sub_links])
            for a in raw
        ]
    }


def _ai_overview(tree: HTMLParser, warnings: list[str]) -> dict:
    root = find_aio_root(tree)
    if root is None:
        return {}
    parsed = parse_aio(root)
    warnings.extend(parsed.warnings)
    if not (parsed.intro or parsed.sections or parsed.sources):
        return {}
    return {
        "ai_overview": AiOverview(
            intro=parsed.intro,
            sections=[AioSection(title=s.title, text=s.text) for s in parsed.sections],
            sources=[AioSource(title=s.title, url=s.url, snippet=s.snippet) for s in parsed.sources],
        )
    }


def _knowledge_panel(tree: HTMLParser, warnings: list[str]) -> dict:
    kp = parse_knowledge_panel(tree)
    if kp is None:
        return {}
    return {"knowledge_panel": KnowledgePanel(title=kp.title, subtitle=kp.subtitle, description=kp.description, source_url=kp.source_url, facts=kp.facts)}


def _number_of_results(tree: HTMLParser, warnings: list[str]) -> dict:
    return {"number_of_results": parse_number_of_results(tree)}


def _suggestions(tree: HTMLParser, warnings: list[str]) -> dict:
    return {"suggestions": parse_suggestions(tree)}


def _corrections(tree: HTMLParser, warnings: list[str]) -> dict:
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
