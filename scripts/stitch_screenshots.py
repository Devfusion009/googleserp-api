"""Stitch Chrome-extension screenshots (saved via computer save_to_disk=true)
into one tall tests/fixtures/<slug>.png.

Usage: python scripts/stitch_screenshots.py <slug> --since <unix_ts>
Picks every screenshot under /tmp/claude-chrome-screenshots-*/ newer than
--since, in mtime order, and stacks them top to bottom (some vertical overlap
between shots is normal and harmless - this is a human-readable reference
image, not a pixel-diff fixture).
"""
import argparse
import glob
import sys
import time
from pathlib import Path

from PIL import Image

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--since", type=float, required=True, help="unix timestamp; only newer screenshots are used")
    a = ap.parse_args()

    files = sorted(
        (p for p in glob.glob("/tmp/claude-chrome-screenshots-*/*.jpg") if Path(p).stat().st_mtime >= a.since),
        key=lambda p: Path(p).stat().st_mtime,
    )
    if not files:
        sys.exit(f"No screenshots newer than {a.since} found.")
    imgs = [Image.open(p).convert("RGB") for p in files]
    w = max(im.width for im in imgs)
    h = sum(im.height for im in imgs)
    out = Image.new("RGB", (w, h), "white")
    y = 0
    for im in imgs:
        out.paste(im, (0, y))
        y += im.height
    out_path = FIXTURES / f"{a.slug}.png"
    out.save(out_path)
    print(f"stitched {len(files)} shots -> {out_path} ({out.size[0]}x{out.size[1]})")


if __name__ == "__main__":
    main()
