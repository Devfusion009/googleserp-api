"""An AI Overview shown as the answer of a People Also Ask question belongs to that question,
not to the searched query (seen on 'flights to brussels from shanghai')."""
from selectolax.parser import HTMLParser

from app.classify import find_aio_root
from app.parsers.aio import parse_aio

PAD = " filler text for this block." * 12


def _page(main_first: bool) -> str:
    paa = (f'<div class="wQiwMc related-question-pair" data-q="Are there direct flights from Brussels to China?">'
           f'<div role="heading" aria-level="2"><strong>AI Overview</strong></div>'
           f'<div class="n6owBd">Yes, direct flights operate from Brussels to China.{PAD}</div></div>')
    main = (f'<div id="main"><div role="heading" aria-level="2"><strong>AI Overview</strong></div>'
            f'<div class="n6owBd">Nonstop flights from Shanghai to Brussels take about 12 hours.{PAD}</div></div>')
    return f"<html><body><div id='rso'>{main + paa if main_first else paa + main}</div></body></html>"


def test_the_overview_of_the_query_is_used_when_a_people_also_ask_overview_comes_first():
    root = find_aio_root(HTMLParser(_page(main_first=False)))
    assert root is not None and root.attributes.get("id") == "main"
    assert parse_aio(root).intro[0].startswith("Nonstop flights from Shanghai")


def test_a_page_with_only_a_people_also_ask_overview_has_no_overview_of_the_query():
    paa_only = _page(main_first=False).replace('<div id="main">', '<div id="main" hidden-x="1" data-drop="1">')
    tree = HTMLParser(_page(main_first=False))
    for n in tree.css("#main"):
        n.decompose()
    assert find_aio_root(tree) is None
