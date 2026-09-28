"""State shared by the block parsers while one page is parsed."""
from dataclasses import dataclass, field

from ..links import LinkMap


@dataclass
class Gap:
    """Something visible on the page that could not be extracted completely,
    e.g. a result whose destination URL is unknown. Any gap fails the page:
    an incomplete extraction is never returned as a valid result."""

    field: str  # "organic", "paid" or "ai_overview"
    reason: str


@dataclass
class ParseContext:
    links: LinkMap = field(default_factory=LinkMap)
    warnings: list[str] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)

    def gap(self, field_name: str, reason: str) -> None:
        self.gaps.append(Gap(field_name, reason))
        self.warnings.append(f"incomplete {field_name}: {reason}")

    def link_problem(self, href: str | None) -> str:
        """Why `href` has no destination, for a gap message."""
        if self.links.is_unresolved_goto(href):
            return "destination behind Google's /goto redirect was not resolved"
        return f"no usable link (href={(href or '')[:60]!r})"
