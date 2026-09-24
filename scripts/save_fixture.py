"""Move a page saved from Chrome into tests/fixtures/<slug>.html (+ .png).

Usage: python scripts/save_fixture.py t_mobile

In Chrome DevTools Console run this (downloads the live page as page.html):
  (()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([document.documentElement.outerHTML],{type:'text/html'}));a.download='page.html';a.click()})()
Then DevTools > Ctrl+Shift+P > "Capture full size screenshot" (downloads a .png).

This script takes the newest .html and newest .png from ~/Downloads (last 30 min).
With --clipboard it reads the HTML from the clipboard instead.
"""
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
# Chrome's download dir and the screenshot dir vary by system config, so check the
# common spots and pick the newest matching file across all of them.
SEARCH_DIRS = [
    Path.home() / "Downloads",
    Path.home() / "Desktop" / "Downloads",
    Path.home() / "Pictures" / "Screenshots",
    Path.home(),  # some browser windows/profiles default to the home dir itself
]
MAX_AGE_S = 30 * 60


def clipboard() -> str:
    system = platform.system()
    if system == "Darwin":
        cmd = ["pbpaste"]
    elif system == "Windows":
        cmd = ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"]
    else:
        cmd = ["xclip", "-o", "-selection", "clipboard"]
    return subprocess.run(cmd, capture_output=True, check=True).stdout.decode("utf-8", "replace")


def newest(pattern: str) -> Path | None:
    files = [p for d in SEARCH_DIRS if d.is_dir() for p in d.glob(pattern)
             if time.time() - p.stat().st_mtime < MAX_AGE_S]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def looks_like_page(html: str) -> bool:
    return html.lstrip().lower().startswith("<html") and "</html>" in html[-200:].lower()


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    slug = args[0].removesuffix(".html")
    out_html, out_png = FIXTURES / f"{slug}.html", FIXTURES / f"{slug}.png"

    if "--clipboard" in sys.argv:
        html, src = clipboard(), None
        if not looks_like_page(html):
            sys.exit(f"That does not look like a full page ({len(html)} chars). Save it again.")
        out_html.write_text(html, encoding="utf-8")
        print(f"saved {out_html} ({len(html):,} chars)")
    else:
        src = newest("*.html")
        if src is not None:
            html = src.read_text(encoding="utf-8", errors="replace")
            if not looks_like_page(html):
                sys.exit(f"That does not look like a full page ({len(html)} chars). Save it again.")
            out_html.write_text(html, encoding="utf-8")
            src.unlink()
            print(f"saved {out_html} ({len(html):,} chars)")
        elif out_html.exists():
            print(f"html already there: {out_html}")
        else:
            sys.exit("No .html downloaded in the last 30 min. Run the Console command first.")

    png = newest("*.png")
    if png:
        shutil.move(str(png), out_png)
        print(f"saved {out_png} (from {png.name})")
    elif out_png.exists():
        print(f"screenshot already there: {out_png}")
    else:
        print(f"screenshot MISSING - capture it, then run this again or save it as {out_png}")


if __name__ == "__main__":
    main()
