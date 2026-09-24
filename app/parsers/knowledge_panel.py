"""Parse the right-hand Knowledge Panel from #rhs.

Verified against exactly one real fixture (eiffel_tower.html) - it's the only
one of the 16 corpus pages with a traditional entity-style panel here (apple.html
and t_mobile.html have an empty placeholder #rhs; their "About X" info comes from
a different, AI-generated box next to the AI Overview, which is out of scope for
this field). Treat these hooks as provisional until more real KP pages confirm
them - see PROGRESS.md.

Hooks:
  - #rhs holding nothing but a "Complementary Results" placeholder -> no panel.
  - Header stack: repeated `div.WcZOu` elements in order - title, then subtitle
    (a category label like "Historical landmark"), then address, hours, etc.
  - Description: `[data-attrid="description"]`, inside it a `.kno-rdesc` block
    with an `<h3>` label ("Description") we drop, the description text, and a
    trailing attribution link (its href is also the cleanest source_url we get -
    a real, direct link, not Google-wrapped).
  - Facts: every `[data-attrid^="kc:/"]` that has a `.w8qArf` label span - the
    ones without one are action buttons/edit links, not facts, and are skipped.
"""
import logging
from dataclasses import dataclass, field

from selectolax.parser import Node

from .misc import clean_prose, clean_text

# Some fact values (seen on "Hours") nest a hidden feedback widget right in the
# same container as the real value; cut it off if it shows up.
_FACT_JUNK_MARKERS = ("Suggest new", "Thanks for your feedback")

log = logging.getLogger("serp.parsers.knowledge_panel")

HEADER_CLASS = "WcZOu"
LABEL_CLASS = "w8qArf"


@dataclass
class ParsedKnowledgePanel:
    title: str | None = None
    subtitle: str | None = None
    description: str | None = None
    source_url: str | None = None
    facts: dict[str, str] = field(default_factory=dict)


def _parse_description(rhs: Node) -> tuple[str | None, str | None]:
    node = rhs.css_first('[data-attrid="description"] .kno-rdesc')
    if node is None:
        return None, None
    link = node.css_first("a[href]")
    source_url = link.attributes.get("href") if link else None
    label = node.css_first("h3")
    label_text = clean_text(label.text(strip=True)) if label else None
    full = clean_text(node.text(separator=" ", strip=True))
    if full and label_text and full.startswith(label_text):
        full = full[len(label_text):].strip()
    if full and link:
        attribution = clean_text(link.text(strip=True))
        if attribution and full.endswith(attribution):
            full = full[: -len(attribution)].strip()
    return (full or None), source_url


def _parse_facts(rhs: Node) -> dict[str, str]:
    facts: dict[str, str] = {}
    for node in rhs.css('[data-attrid^="kc:/"]'):
        label_node = node.css_first(f".{LABEL_CLASS}")
        if label_node is None:
            continue
        label = clean_text(label_node.text(strip=True))
        if not label:
            continue
        label = label.rstrip(":").strip()
        # The value is the label's own sibling, not the whole attrid element -
        # some facts (e.g. hours) nest a much bigger expandable widget further
        # down in the same [data-attrid] block that we don't want to sweep in.
        # The label is always the first child of its parent in every fact we've
        # seen, so we skip position 0 rather than compare node identity
        # (selectolax hands back a fresh wrapper object per traversal, so
        # `is`/`==` never match the "same" node against label_node itself).
        siblings = list(label_node.parent.iter())[1:]
        value = clean_prose(" ".join(s.text(separator=" ", strip=True) for s in siblings))
        if value:
            for marker in _FACT_JUNK_MARKERS:
                idx = value.find(marker)
                if idx != -1:
                    value = value[:idx].strip()
        if value and label not in facts:
            facts[label] = value
    return facts


def parse_knowledge_panel(tree) -> ParsedKnowledgePanel | None:
    rhs = tree.css_first("#rhs")
    if rhs is None:
        return None
    headers = [clean_text(n.text(strip=True)) for n in rhs.css(f"div.{HEADER_CLASS}")]
    headers = [h for h in headers if h]
    description, source_url = _parse_description(rhs)
    facts = _parse_facts(rhs)

    if not headers and not description and not facts:
        return None  # empty #rhs placeholder - no panel on this page

    title = headers[0] if headers else None
    subtitle = headers[1] if len(headers) > 1 else None
    if not source_url:
        for h in headers:
            if h.startswith("http://") or h.startswith("https://"):
                source_url = h
                break

    if title is None:
        log.warning("knowledge panel present (facts/description found) but no title header")

    return ParsedKnowledgePanel(title=title, subtitle=subtitle, description=description, source_url=source_url, facts=facts)
