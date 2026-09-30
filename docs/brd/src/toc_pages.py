"""Find the page each numbered H1 lands on in the exported PDF (for the static contents list)."""
import json, re, sys
import pymupdf

pdf = pymupdf.open(sys.argv[1])
titles = json.loads(sys.argv[2])
found = {}
for i, page in enumerate(pdf):
    for line in page.get_text("text").splitlines():
        norm = re.sub(r"\s+", " ", line).strip()
        for n, t in titles:
            if str(n) not in found and norm == f"{n} {t}" and i > 2:
                found[str(n)] = i + 1
        m = re.match(r"^Figure (\d+) \S", norm)
        if m and i > 2 and f"fig{m.group(1)}" not in found:
            found[f"fig{m.group(1)}"] = i + 1
print(json.dumps(found))
missing = [n for n, _ in titles if str(n) not in found]
if missing:
    print("MISSING", missing, file=sys.stderr)
