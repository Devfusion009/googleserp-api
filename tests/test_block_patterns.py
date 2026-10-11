"""BLOCKED_URL_PATTERNS, matched the way Chrome's Network.setBlockedURLs does ('*' only)."""
import re

import pytest

from app.config import Settings

PATTERNS = [re.compile("^" + ".*".join(map(re.escape, p.split("*"))) + "$")
            for p in Settings(_env_file=None).blocked_url_patterns.split(",")]


def blocked(url: str) -> bool:
    return any(p.match(url) for p in PATTERNS)


@pytest.mark.parametrize("url", [
    "https://www.google.com/logos/doodle.png", "https://example.com/a.jpg?w=200", "https://encrypted-tbn0.gstatic.com/images?q=x",
    "https://fonts.gstatic.com/s/roboto/v1/x.woff2", "https://upload.wikimedia.org/wikipedia/commons/a/b.svg"])
def test_images_media_and_fonts_are_blocked(url):
    assert blocked(url)


@pytest.mark.parametrize("url", [
    # live: "*.ico*" matched this stylesheet and Polish Wikipedia rendered unstyled
    "https://pl.wikipedia.org/w/load.php?lang=pl&modules=skins.vector.icons%7Cskins.vector.styles&only=styles",
    "https://www.google.com/xjs/_/js/k=xjs.s.en.KMXk7dRWMAY.2023.O/am=AAA", "https://www.gstatic.com/og/_/ss/k=og.asy.x.css",
    "https://www.google.com/search?q=png+to+jpg"])
def test_pages_scripts_and_styles_are_not(url):
    assert not blocked(url)
