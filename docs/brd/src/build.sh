#!/usr/bin/env bash
# Rebuild every diagram, the Word document and the PDF.
# Needs: node + the npm packages in package.json, Playwright's Chromium, LibreOffice, python3 + pymupdf.
set -euo pipefail
cd "$(dirname "$0")"
OUT=..
[ "${SKIP_IMAGES:-0}" = 1 ] || { node d_business.js && node d_tech.js && node d_db.js; }
TITLES='[[1,"Summary"],[2,"Client pain points and how we solve them"],[3,"Business requirements"],[4,"Solution architecture (business view)"],[5,"System architecture (technical)"],[6,"Backend architecture"],[7,"How one request flows"],[8,"Database design"],[9,"API specification"],[10,"Tech stack"],[11,"Infrastructure and deployment"],[12,"Non-functional requirements"],[13,"Security and compliance"],[14,"Monitoring and alerting"],[15,"Delivery plan"],[16,"Risks and mitigations"],[17,"Open decisions for the client"],[18,"Glossary"]]'
rm -f toc_pages.json
TMP=$(mktemp -d)
node build_docx.js "$TMP/pass1.docx"
soffice --headless --convert-to pdf --outdir "$TMP" "$TMP/pass1.docx" >/dev/null 2>&1
python3 toc_pages.py "$TMP/pass1.pdf" "$TITLES" > toc_pages.json
cat toc_pages.json
node build_docx.js "$OUT/Google_SERP_API_BRD.docx"
soffice --headless --convert-to pdf --outdir "$OUT" "$OUT/Google_SERP_API_BRD.docx" >/dev/null 2>&1
python3 toc_pages.py "$OUT/Google_SERP_API_BRD.pdf" "$TITLES" > "$TMP/check.json"
diff <(python3 -c 'import json,sys;print(json.dumps(json.load(open("toc_pages.json")),sort_keys=True))') <(python3 -c 'import json,sys;print(json.dumps(json.load(open(sys.argv[1])),sort_keys=True))' "$TMP/check.json") && echo "contents page numbers verified"
rm -rf "$TMP"
