# Business Requirements & Technical Specification

- `Google_SERP_API_BRD.pdf` — the document to read and share
- `Google_SERP_API_BRD.docx` — the same document, editable in Word
- `images/` — every diagram as a high-resolution PNG (also embedded in both files)
- `src/` — the scripts that draw the diagrams and build the documents

## Rebuilding

The diagrams are SVG drawn in code and rendered with headless Chromium; the Word
file is built with `docx`; the PDF is exported from the Word file by LibreOffice,
so the two always match. Contents page numbers are found by a first export and
checked after the second.

```bash
cd docs/brd/src
npm install                 # docx, lucide-static
./build.sh                  # needs Playwright's Chromium, LibreOffice Writer, python3 + pymupdf
SKIP_IMAGES=1 ./build.sh    # text-only changes: reuse the existing PNGs
```
