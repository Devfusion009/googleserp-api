// Builds the BRD as a Word document. The PDF is exported from this file by
// LibreOffice (see build.sh) so both formats always match.
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell, WidthType, ShadingType,
  BorderStyle, AlignmentType, HeadingLevel, PageOrientation, Header, Footer, PageNumber, TabStopType,
  LevelFormat, VerticalAlign, Bookmark, InternalHyperlink, HorizontalPositionRelativeFrom, VerticalPositionRelativeFrom,
  TableLayoutType, SectionType,
} = require('docx');

const IMG = path.join(__dirname, '..', 'images');
const OUT = process.argv[2] || path.join(__dirname, '..', 'Google_SERP_API_BRD.docx');
const PAGES = fs.existsSync(path.join(__dirname, 'toc_pages.json')) ? JSON.parse(fs.readFileSync(path.join(__dirname, 'toc_pages.json'))) : {};

// ------------------------------------------------------------------ palette
const NAVY = '0F2A44', BLUE = '2F86B0', TEAL = '0E9682', INK = '1E293B', MUTED = '64748B', LINE = 'D5DEE8';
const SOFT = 'F1F5F9', SOFTER = 'F8FAFC';
const FONT = 'Calibri', MONO = 'Consolas';

// Letter, portrait and landscape bodies (DXA: 1440 = 1 inch)
const P_W = 12240, P_H = 15840, P_M = 1224;           // 0.85" margins
const P_BODY = P_W - 2 * P_M;                           // 9792 = 6.8"
const L_MX = 1080, L_MT = 864, L_MB = 792;             // landscape margins
const L_BODY = P_H - 2 * L_MX;                          // 13680 = 9.5"

// ------------------------------------------------------------- inline markup
// **bold**, `code`, and {c:HEX|text} for coloured text.
function runs(str, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\{c:[0-9A-F]{6}\|[^}]+\})/g;
  let last = 0, m;
  const push = (t, o) => { if (t) out.push(new TextRun({ text: t, font: FONT, ...base, ...o })); };
  while ((m = re.exec(str))) {
    push(str.slice(last, m.index), {});
    const tok = m[0];
    if (tok.startsWith('**')) push(tok.slice(2, -2), { bold: true });
    else if (tok.startsWith('`')) push(tok.slice(1, -1), { font: MONO, size: Math.max((base.size || 21) - 2, 14), color: base.color || '9A3412' });
    else { const [, hex, t] = tok.match(/\{c:([0-9A-F]{6})\|([^}]+)\}/); push(t, { color: hex, bold: true }); }
    last = m.index + tok.length;
  }
  push(str.slice(last), {});
  return out;
}

const P = (str, o = {}) => new Paragraph({ children: runs(str, o.run || {}), spacing: { after: o.after ?? 120, before: o.before ?? 0, line: o.line ?? 276 }, alignment: o.align, keepNext: o.keepNext, indent: o.indent });
const small = (str, o = {}) => P(str, { ...o, run: { size: 17, color: MUTED, ...(o.run || {}) } });

let figNo = 0;
const bookmarks = [];
const figList = [];
function H1(num, title, o = {}) {
  const id = `sec${num}`;
  bookmarks.push({ id, num, title });
  return new Paragraph({
    heading: HeadingLevel.HEADING_1, pageBreakBefore: o.pageBreak !== false, keepNext: true,
    children: [new Bookmark({ id, children: [
      new TextRun({ text: `${num}`, color: TEAL, font: FONT }),
      new TextRun({ text: '   ', font: FONT }),
      new TextRun({ text: title, font: FONT }),
    ] })],
  });
}
const H2 = (t, o = {}) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun({ text: t, font: FONT })], keepNext: true, pageBreakBefore: !!o.pageBreak });
const H3 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun({ text: t, font: FONT })], keepNext: true });
const bullets = (items, o = {}) => items.map((t) => new Paragraph({ numbering: { reference: 'dots', level: 0 }, children: runs(t, o.run || {}), spacing: { after: 70, line: 264 } }));
const spacer = (after = 120) => new Paragraph({ children: [], spacing: { after } });

// ------------------------------------------------------------------ figures
function pngSize(file) {
  const b = fs.readFileSync(file);
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20), data: b };
}
function figure(name, caption, maxWIn, maxHIn) {
  const { w, h, data } = pngSize(path.join(IMG, name + '.png'));
  let wIn = maxWIn, hIn = (h / w) * wIn;
  if (hIn > maxHIn) { hIn = maxHIn; wIn = (w / h) * hIn; }
  figNo += 1;
  figList.push([figNo, caption]);
  return [
    new Paragraph({ alignment: AlignmentType.CENTER, keepNext: true, spacing: { before: 60, after: 60 },
      children: [new ImageRun({ type: 'png', data, transformation: { width: Math.round(wIn * 96), height: Math.round(hIn * 96) }, altText: { title: caption, description: caption, name } })] }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 160 }, children: [
      new TextRun({ text: `Figure ${figNo}  `, bold: true, size: 17, color: NAVY, font: FONT }),
      new TextRun({ text: caption, size: 17, color: MUTED, font: FONT, italics: true })] }),
  ];
}

// ------------------------------------------------------------------- tables
const border = (c = LINE, sz = 4) => ({ style: BorderStyle.SINGLE, size: sz, color: c });
const NOB = { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' };
function cellParas(v, o) {
  const arr = Array.isArray(v) ? v : [v];
  return arr.map((t, i) => {
    const str = String(t), bullet = str.startsWith('- ');
    return new Paragraph({ children: runs(bullet ? str.slice(2) : str, { size: o.size || 18, color: o.color || INK, bold: o.bold }), numbering: bullet ? { reference: 'cell', level: 0 } : undefined, spacing: { after: i === arr.length - 1 ? 0 : 50, line: 252 }, alignment: o.align });
  });
}
function table(headers, rows, o = {}) {
  const total = o.total || P_BODY;
  const widths = (o.widths || headers.map(() => 1));
  const sum = widths.reduce((a, b) => a + b, 0);
  const cw = widths.map((w) => Math.round((w / sum) * total));
  cw[cw.length - 1] += total - cw.reduce((a, b) => a + b, 0);
  const mk = (v, i, hdr, rowIdx, rowOpt = {}) => new TableCell({
    width: { size: cw[i], type: WidthType.DXA },
    shading: { fill: hdr ? (o.headFill || NAVY) : (rowOpt.fill?.[i] || rowOpt.rowFill || (o.zebra !== false && rowIdx % 2 ? SOFTER : 'FFFFFF')), type: ShadingType.CLEAR, color: 'auto' },
    margins: { top: 55, bottom: 55, left: 110, right: 110 },
    verticalAlign: VerticalAlign.CENTER,
    children: cellParas(v, hdr ? { size: 17, color: 'FFFFFF', bold: true } : { size: o.size || 18, bold: o.boldFirst && i === 0, color: rowOpt.color?.[i], align: o.align?.[i] }),
  });
  const trs = [];
  if (headers.length && !o.noHeader) trs.push(new TableRow({ tableHeader: true, cantSplit: true, children: headers.map((h, i) => mk(h, i, true)) }));
  rows.forEach((r, ri) => {
    const cells = r.cells || r;
    trs.push(new TableRow({ cantSplit: true, children: cells.map((v, i) => mk(v, i, false, ri, r)) }));
  });
  return new Table({
    width: { size: total, type: WidthType.DXA }, columnWidths: cw, layout: TableLayoutType.FIXED,
    borders: { top: border(), bottom: border(), left: border(), right: border(), insideHorizontal: border(), insideVertical: border() },
    rows: trs,
  });
}

// Coloured callout: one cell, tinted fill, thick left rule.
function callout(title, lines, o = {}) {
  const fill = o.fill || 'EFF6FF', edge = o.edge || BLUE, tc = o.titleColor || NAVY;
  const kids = [];
  if (title) kids.push(new Paragraph({ children: [new TextRun({ text: title, bold: true, size: 20, color: tc, font: FONT })], spacing: { after: 80 } }));
  for (const l of lines) {
    if (l.startsWith('- ')) kids.push(new Paragraph({ numbering: { reference: 'dots', level: 0 }, children: runs(l.slice(2), { size: 19, color: o.textColor || INK }), spacing: { after: 50, line: 252 } }));
    else kids.push(new Paragraph({ children: runs(l, { size: 19, color: o.textColor || INK }), spacing: { after: 60, line: 252 } }));
  }
  return new Table({
    width: { size: o.total || P_BODY, type: WidthType.DXA }, columnWidths: [o.total || P_BODY], layout: TableLayoutType.FIXED,
    borders: { top: NOB, bottom: NOB, right: NOB, left: { style: BorderStyle.SINGLE, size: 24, color: edge }, insideHorizontal: NOB, insideVertical: NOB },
    rows: [new TableRow({ cantSplit: true, children: [new TableCell({ width: { size: o.total || P_BODY, type: WidthType.DXA }, shading: { fill, type: ShadingType.CLEAR, color: 'auto' }, margins: { top: 140, bottom: 140, left: 220, right: 200 }, children: kids })] })],
  });
}

// KPI tiles: big number + label.
function tiles(items, o = {}) {
  const total = o.total || P_BODY, n = items.length, w = Math.floor(total / n);
  const cells = items.map(([big, label, sub, col]) => new TableCell({
    width: { size: w, type: WidthType.DXA }, shading: { fill: o.fill || 'F4F8FC', type: ShadingType.CLEAR, color: 'auto' },
    margins: { top: 160, bottom: 160, left: 160, right: 120 },
    borders: { top: { style: BorderStyle.SINGLE, size: 24, color: col || BLUE }, bottom: border('FFFFFF', 12), left: border('FFFFFF', 12), right: border('FFFFFF', 12) },
    children: [
      new Paragraph({ children: [new TextRun({ text: big, bold: true, size: 44, color: col || NAVY, font: FONT })], spacing: { after: 40 } }),
      new Paragraph({ children: [new TextRun({ text: label, bold: true, size: 18, color: INK, font: FONT })], spacing: { after: 20 } }),
      new Paragraph({ children: [new TextRun({ text: sub, size: 16, color: MUTED, font: FONT })], spacing: { after: 0 } }),
    ],
  }));
  return new Table({ width: { size: w * n, type: WidthType.DXA }, columnWidths: items.map(() => w), layout: TableLayoutType.FIXED,
    borders: { top: NOB, bottom: NOB, left: NOB, right: NOB, insideHorizontal: NOB, insideVertical: border('FFFFFF', 24) },
    rows: [new TableRow({ cantSplit: true, children: cells })] });
}

function codeBlock(lines, o = {}) {
  const total = o.total || P_BODY;
  return new Table({ width: { size: total, type: WidthType.DXA }, columnWidths: [total], layout: TableLayoutType.FIXED,
    borders: { top: border(LINE), bottom: border(LINE), left: border(LINE), right: border(LINE), insideHorizontal: NOB, insideVertical: NOB },
    rows: [new TableRow({ cantSplit: true, children: [new TableCell({ width: { size: total, type: WidthType.DXA }, shading: { fill: 'F6F8FB', type: ShadingType.CLEAR, color: 'auto' }, margins: { top: 120, bottom: 120, left: 200, right: 200 },
      children: lines.map((l) => new Paragraph({ spacing: { after: 0, line: 240 }, children: [new TextRun({ text: l, font: MONO, size: 15, color: '1E293B' })] })) })] })] });
}

// Rating chip text for risk tables.
const lvl = (t) => ({ High: '{c:B91C1C|High}', Medium: '{c:B45309|Medium}', Low: '{c:15803D|Low}' }[t] || t);

// ----------------------------------------------------------- header / footer
const header = (land) => new Header({ children: [new Paragraph({
  border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: LINE, space: 4 } },
  tabStops: [{ type: TabStopType.RIGHT, position: land ? L_BODY : P_BODY }],
  children: [
    new TextRun({ text: 'Google SERP API', bold: true, size: 16, color: NAVY, font: FONT }),
    new TextRun({ text: '  ·  Business Requirements & Technical Specification', size: 16, color: MUTED, font: FONT }),
    new TextRun({ text: '\tv1.0  ·  Confidential', size: 16, color: MUTED, font: FONT }),
  ] })] });
const footer = (land) => new Footer({ children: [new Paragraph({
  tabStops: [{ type: TabStopType.RIGHT, position: land ? L_BODY : P_BODY }],
  children: [
    new TextRun({ text: 'Devfusion Engineering  ·  30 September 2026', size: 16, color: MUTED, font: FONT }),
    new TextRun({ children: ['\tPage ', PageNumber.CURRENT], size: 16, color: MUTED, font: FONT }),
  ] })] });

const portrait = (children, o = {}) => ({
  properties: { type: o.type || SectionType.NEXT_PAGE, page: { size: { width: P_W, height: P_H, orientation: PageOrientation.PORTRAIT }, margin: { top: P_M, bottom: P_M, left: P_M, right: P_M, header: 560, footer: 520 } } },
  headers: { default: header(false) }, footers: { default: footer() }, children,
});
const landscape = (children) => ({
  properties: { type: SectionType.NEXT_PAGE, page: { size: { width: P_W, height: P_H, orientation: PageOrientation.LANDSCAPE }, margin: { top: L_MT, bottom: L_MB, left: L_MX, right: L_MX, header: 400, footer: 380 } } },
  headers: { default: header(true) }, footers: { default: footer(true) }, children,
});
// Landscape heading paragraphs must not force an extra page break (the section already starts one).
const LH1 = (num, title) => H1(num, title, { pageBreak: false });

// ======================================================================= BODY
const S = []; // sections

// ---- cover (full-bleed image, its own section, no header/footer)
{
  const { data } = pngSize(path.join(IMG, '00_cover.png'));
  S.push({
    properties: { page: { size: { width: P_W, height: P_H }, margin: { top: 0, bottom: 0, left: 0, right: 0, header: 0, footer: 0 } } },
    children: [new Paragraph({ spacing: { after: 0, line: 240 }, children: [new ImageRun({ type: 'png', data, transformation: { width: 816, height: 1056 },
      floating: { horizontalPosition: { relative: HorizontalPositionRelativeFrom.PAGE, offset: 0 }, verticalPosition: { relative: VerticalPositionRelativeFrom.PAGE, offset: 0 }, behindDocument: true, allowOverlap: true },
      altText: { title: 'Cover', description: 'Google SERP API - Business Requirements & Technical Specification', name: 'cover' } })] })],
  });
}

// ---- document control + contents
const tocTitles = [
  [1, 'Summary'], [2, 'Client pain points and how we solve them'], [3, 'Business requirements'], [4, 'Solution architecture (business view)'],
  [5, 'System architecture (technical)'], [6, 'Backend architecture'], [7, 'How one request flows'], [8, 'Database design'],
  [9, 'API specification'], [10, 'Tech stack'], [11, 'Infrastructure and deployment'], [12, 'Non-functional requirements'],
  [13, 'Security and compliance'], [14, 'Monitoring and alerting'], [15, 'Delivery plan'], [16, 'Risks and mitigations'],
  [17, 'Open decisions for the client'], [18, 'Glossary'],
];
const tocLine = (num, title) => new Paragraph({
  spacing: { after: 70 },
  tabStops: [{ type: TabStopType.LEFT, position: 560 }, { type: TabStopType.RIGHT, position: P_BODY, leader: 'dot' }],
  children: [new InternalHyperlink({ anchor: `sec${num}`, children: [
    new TextRun({ text: `${num}`, bold: true, color: TEAL, size: 21, font: FONT }),
    new TextRun({ text: `\t${title}`, color: INK, size: 21, font: FONT }),
    new TextRun({ text: `\t${PAGES[num] || '00'}`, color: MUTED, size: 21, font: FONT }),
  ] })],
});

S.push(portrait([
  new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun({ text: 'Document control', font: FONT })] }),
  table(['Version', 'Date', 'Author', 'What changed'], [
    ['1.0', '30 Sep 2026', 'Devfusion Engineering', 'First complete draft for client review.'],
  ], { widths: [1, 1.4, 2, 4.2] }),
  spacer(200),
  H3('Review and sign-off'),
  table(['Role', 'Name', 'Decision', 'Date'], [
    ['Client product owner', '', '', ''], ['Client technical lead', '', '', ''], ['Devfusion engineering lead', '', '', ''],
  ], { widths: [3, 3, 2, 1.6] }),
  spacer(200),
  H3('How to read this document'),
  table(['If you are…', 'Start with'], [
    ['A business stakeholder', 'Sections 1–4, 15 and 16. They explain the problem, the solution and the plan without technical detail.'],
    ['An engineer or architect', 'Sections 5–14. Diagrams first, tables second.'],
    ['Signing off', 'Section 17 lists the decisions we need from you.'],
  ], { widths: [2.2, 6] }),
  spacer(200),
  H3('Related material'),
  ...bullets([
    '`README.md` in the repository: setup, the exact API contract and parsing rules.',
    '`PROGRESS.md`: build history, client decisions and what was verified, phase by phase.',
    'Benchmark reports (`reports/<run_id>/report.md`): produced by `bench/run_bench.py` on every run.',
  ]),
  new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun({ text: 'Contents', font: FONT })] }),
  ...tocTitles.map(([n, t]) => tocLine(n, t)),
  spacer(160),
  { lofSlot: true },
  spacer(160),
  callout('A note on numbers', [
    'Every figure marked **target** is a goal the benchmark must prove, not a measurement. Live numbers do not exist yet: the development IP is blocked by Google on the first request, so the first real measurement is the proxy smoke test in week 1 (section 15).',
  ], { fill: 'FFFBEB', edge: 'D97706', titleColor: '92400E' }),
]));

// ---- 1 Summary + 2 pain points + 3 business requirements + 4 solution
S.push(portrait([
  H1(1, 'Summary', { pageBreak: false }),
  P('The client needs live Google results as clean JSON they can trust: the paid ads, the organic links, the full AI Overview with every source, and the knowledge panel. The engine that does this is **built and tested** against 16 real Google pages. This document describes how to run it as a production service and how we will prove it meets the two numbers that matter.'),
  spacer(60),
  tiles([
    ['≥ 98%', 'Valid results', 'per test corpus', BLUE],
    ['≤ 2.0 s', 'P95 response time', 'measured by the client', TEAL],
    ['0', 'Made-up fields', 'missing = null, incomplete = error', '7C3AED'],
    ['100%', 'Google requests counted', 'in every response', 'B45309'],
  ]),
  small('All four are targets. They become results after the week-1 smoke test and the week-9 acceptance run.', { before: 80, after: 200 }),
  H2('Where we are today'),
  table(['Built and tested', 'Waiting on live proxy access', 'What this document adds'], [
    [[
      '- `POST /serp` and `GET /health` with the exact client schema',
      '- 7 parsers checked against 16 real pages',
      '- Completeness gate and honest error codes',
      '- Real destinations for `/goto` links',
      '- Proxy support by config only',
      '- Benchmark tool and 183 automated tests',
    ], [
      '- The first run through the client\'s US residential proxies',
      '- Real valid rate, P95 and traffic per page',
      '- AI Overview wait and expand on live Google',
      '- `/goto` resolution on Google\'s own servers',
    ], [
      '- A production platform on AWS',
      '- A database for keys, usage and results',
      '- Dashboards, alerts and an hourly canary',
      '- A 10-week plan to go-live',
    ]],
  ], { widths: [1, 1, 1], zebra: false }),
  spacer(120),
  P('The honest summary: the hard part — reading Google\'s page correctly and refusing to return anything half-done — is solved. What is left is running it at scale through the right proxies and proving the speed target, especially for queries with an AI Overview.', { run: { color: INK } }),
  spacer(40),
  callout('What we need from the client to start', [
    '- Proxy credentials and the provider\'s session syntax for the week-1 smoke test (100 MB budget agreed).',
    '- Answers to the open decisions in section 17.',
    '- Expected daily search volume at launch and in 12 months, to size the platform.',
  ], { fill: 'F0FDF4', edge: '16A34A', titleColor: '166534' }),

  H1(2, 'Client pain points and how we solve them'),
  P('These seven problems came up while building and testing the engine. Each one maps to a specific part of the design.'),
  ...figure('02_pain_points', 'Pain points and the fix for each one', 6.5, 7.6),

  H1(3, 'Business requirements'),
  H2('3.1  Goals'),
  table(['#', 'Goal', 'How we measure it', 'Target'], [
    ['G1', 'Reliable data', 'Valid results ÷ all requests, per corpus', '≥ 98%'],
    ['G2', 'Fast answers', 'P95 end-to-end time, failures included', '≤ 2,000 ms'],
    ['G3', 'Data you can trust', 'Fields that are guessed or rebuilt', '0'],
    ['G4', 'Clear usage and cost', 'Google requests counted in `requests_used`', '100%'],
    ['G5', 'Controlled proxy spend', 'Bytes per page reported; runs stop before the budget', 'Every run'],
    ['G6', 'Room to grow', 'More capacity by adding workers, not changing code', 'Linear'],
  ], { widths: [0.5, 1.8, 3.8, 1.3], boldFirst: true }),
  spacer(160),
  H2('3.2  Scope'),
  table(['In scope', 'Out of scope'], [
    [[
      '- Google web search (`google.com/search`), US English first',
      '- Paid ads (top and bottom blocks) and organic results with sub-links',
      '- AI Overview: intro, sections and every source',
      '- Knowledge panel, result count, related searches, spelling fixes',
      '- More than 10 results through extra pages (`&start=10`, `20`, …)',
      '- JSON, or the raw page HTML when asked',
      '- API keys, quotas, usage reports, monitoring, benchmark',
    ], [
      '- Solving or bypassing CAPTCHAs',
      '- Stealth or fingerprint tricks',
      '- Third-party SERP APIs, caches or other data sources',
      '- Images, News, Shopping and other verticals',
      '- Mid-page "in-feed" ads',
      '- People Also Ask, local packs, carousels, flight modules',
      '- Visiting the result websites themselves',
    ]],
  ], { widths: [1, 1], zebra: false }),
  spacer(160),
  H2('3.3  Business rules'),
  callout('What the platform will never do', [
    '- Solve, click or work around a CAPTCHA. A block is reported as `blocked_captcha`.',
    '- Use third-party SERP APIs, scraped caches or any other data source.',
    '- Cache a search result and serve it again. Every answer is a fresh page.',
    '- Make data up. Missing means `null` or empty; incomplete means an error.',
    '- Retry a blocked request on the same IP address.',
    '- Change the client\'s URL. Even an odd one (like `hl=us`) goes to Google byte for byte.',
  ], { fill: 'FEF2F2', edge: 'DC2626', titleColor: '991B1B' }),
  H2('3.4  Who uses it', { pageBreak: true }),
  table(['User', 'What they need'], [
    ['Client developers', 'A stable API, clear error codes, examples and SDKs.'],
    ['Client SEO / analytics team', 'Complete, correct data flowing into their tools every day.'],
    ['Client account owner', 'Usage and cost per API key, per day, without asking us.'],
    ['Devfusion operations', 'Dashboards, alerts and a saved copy of every page that failed.'],
  ], { widths: [2.2, 6], boldFirst: true }),

  spacer(100),
  H2('3.5  Functional requirements'),
  table(['ID', 'Requirement', 'Priority'], [
    ['FR-01', 'Accept `POST /serp` with `url`, `results`, `country`, `language`, `return_json`.', 'Must'],
    ['FR-02', 'Accept only `google.com` / `www.google.com` `/search` links with `q=`; send them exactly as given.', 'Must'],
    ['FR-03', 'For `results` above 10, fetch extra pages with `&start=10`, `20`, … (never `num=`).', 'Must'],
    ['FR-04', 'Return the agreed shape: `status_code`, `requests_used`, `elapsed_time`, `results`, `error`, `error_message`.', 'Must'],
    ['FR-05', 'Extract paid ads, organic results, AI Overview (intro, sections, sources), knowledge panel, count, suggestions, corrections.', 'Must'],
    ['FR-06', 'Resolve `/goto` and `/url` links through Google\'s own redirect. Never rebuild a link from the breadcrumb.', 'Must'],
    ['FR-07', 'Fail the page (`parse_error` / `aio_incomplete`) when anything returned is incomplete.', 'Must'],
    ['FR-08', 'Report blocks, consent walls, degraded pages, timeouts and network failures with the agreed codes.', 'Must'],
    ['FR-09', 'Count every Google request (page loads, retries, `/async`, `/goto`) in `requests_used`.', 'Must'],
    ['FR-10', 'Send debug headers (`X-Request-Id`, `X-Timings`, `X-Google-Requests`, …) outside the JSON body.', 'Must'],
    ['FR-11', 'Authenticate with `X-API-Key`. Enforce a rate limit and a monthly quota per key.', 'Must'],
    ['FR-12', 'Keep the page HTML and a screenshot for every request for 14 days.', 'Should'],
    ['FR-13', 'Usage API: requests, valid, failed, Google requests and bytes per key per day.', 'Should'],
    ['FR-14', 'Admin API: create and revoke keys, set quotas, manage proxy providers.', 'Should'],
    ['FR-15', 'Hourly canary with known queries; alert when a field that used to be filled comes back empty.', 'Should'],
    ['FR-16', 'Batch mode: submit many searches, get a webhook when they are done.', 'Could'],
    ['FR-17', 'Client portal for keys, usage and invoices.', 'Could'],
  ], { widths: [0.8, 6.4, 1], boldFirst: true }),
  spacer(160),
  H2('3.6  Decisions the client has already confirmed'),
  ...bullets([
    'Shopping and product cards are page UI, not AI Overview sources.',
    'Google-hosted sources (e.g. Google Flights) stay. A source that cannot be resolved makes the request incomplete; it is never dropped.',
    '`/goto` lookups, retries and AI Overview follow-ups all count in `requests_used`.',
    'The first live run is a single-session smoke test: it stops at the first CAPTCHA and reports what it did not run.',
  ]),

  H1(4, 'Solution architecture (business view)'),
  P('This is the picture for non-technical readers: what happens between "send a search link" and "get clean data back".'),
  ...figure('04_solution_architecture', 'The solution in one picture', 6.3, 4.85),
  H3('In plain words'),
  ...bullets([
    'You send us a Google search link and your API key.',
    'We open that exact page in a real browser, through a normal US home internet connection — the way a person would.',
    'We read everything you asked for and check that nothing is missing or guessed.',
    'You get clean JSON back, or a clear error that says what went wrong. Either way we keep a copy of the page as proof.',
  ]),
  spacer(80),
  table(['Today (engine)', 'After go-live (platform)'], [
    ['Runs on one machine', 'Runs on AWS across two data centres (availability zones)'],
    ['One browser, one request at a time', 'Many browser slots in parallel, added and removed automatically'],
    ['Logs and saved pages on local disk', 'Dashboards, alerts and a 14-day proof store'],
    ['One API key in a config file', 'A key per team, each with its own quota and usage report'],
  ], { widths: [1, 1.4] }),
]));

// ---- 5 System architecture (landscape figure) + components (portrait)
S.push(landscape([
  LH1(5, 'System architecture (technical)'),
  ...figure('05_system_architecture', 'System architecture: edge, API tier, browser worker fleet, data and operations', 9.5, 6.05),
]));
S.push(portrait([
  H2('5.1  Components'),
  table(['Component', 'What it does', 'Technology'], [
    ['Edge', 'DNS, TLS, WAF rules, load balancing', 'Route 53, ACM, AWS WAF, ALB'],
    ['SERP Gateway', 'API keys, quotas, URL check, hands the job to a slot, builds JSON and debug headers', 'FastAPI on ECS Fargate'],
    ['Job dispatch', 'Gives each request to a free warm browser slot and returns the answer', 'Redis Streams'],
    ['Browser workers', 'Load the page, wait, expand the AI Overview, resolve links, parse, verify, count', 'Playwright + Chromium headless shell on ECS (EC2)'],
    ['Proxy manager', 'One sticky session per slot, rotation after blocks, exit-IP checks, health scores', 'Worker library + Redis'],
    ['Parser registry', '7 parsers: organic, ads, AI Overview, knowledge panel, count, suggestions, corrections', 'selectolax'],
    ['Database', 'Keys, every request, parsed results of valid pages, usage', 'PostgreSQL 16 (RDS Multi-AZ)'],
    ['Proof store', 'Page HTML + screenshot per request', 'Amazon S3, 14-day lifecycle'],
    ['Events & analytics', 'One event per request with timings, bytes and outcome', 'Kinesis Firehose → S3 → Athena'],
    ['Observability', 'Metrics, traces, logs, alerts', 'OpenTelemetry, Prometheus, Grafana, CloudWatch, PagerDuty'],
  ], { widths: [1.6, 4.2, 2.6], boldFirst: true }),
  spacer(200),
  H2('5.2  Why it is built this way'),
  ...bullets([
    '**API and browsers are split.** An API task is light; a browser slot is heavy. Splitting them lets each scale on its own signal and keeps a browser crash away from the API.',
    '**One slot = one browser context + one page + one proxy session.** Everything for one page leaves from one IP, the one Google set its cookies on. A session is never swapped in the middle of a request.',
    '**Headless shell, not full Chrome.** The full browser calls Google on its own (sign-in checks, time sync). That adds traffic and noise the headless shell does not make.',
    '**Warm browsers.** Starting Chromium takes seconds. Browsers start once and stay open, so a request only pays for the page itself.',
    '**Redis carries jobs and counters only.** It never stores a search result, so nothing can be served twice by accident.',
  ]),
]));

// ---- 6 Backend architecture (landscape) + legend (portrait)
S.push(landscape([
  LH1(6, 'Backend architecture'),
  ...figure('06_backend_architecture', 'Backend on AWS — numbers match the steps in the table that follows', 9.5, 6.05),
]));
S.push(portrait([
  H2('6.1  What each numbered step does'),
  table(['#', 'Step', 'Detail'], [
    ['1', 'Client call', 'Client systems call the API over HTTPS with their `X-API-Key`.'],
    ['2', 'Load balancer', 'The ALB ends TLS, AWS WAF drops abusive traffic, requests are spread across gateway tasks.'],
    ['3', 'API gateway', 'Checks the key, quota and URL, stamps a request ID and routes to the right API.'],
    ['4', 'Search API → workers', 'The job goes to a free warm browser slot through Redis Streams.'],
    ['5', 'Cache (Redis)', 'Holds job streams, rate-limit counters, quotas and proxy health. Never search results.'],
    ['6', 'Datastores', 'Requests, parsed results and usage are written to PostgreSQL.'],
    ['7', 'Stream pipeline', 'Every request emits one event: timings, bytes, Google requests, outcome.'],
    ['8', 'S3, Athena, rollups', 'Events land in S3 as Parquet, Athena queries them, daily usage rolls up into PostgreSQL.'],
    ['9', 'Proxies → Google', 'Workers reach Google only through US residential proxies, one sticky session per slot.'],
    ['10', 'Canary & monitoring', 'Known queries run every hour through the front door; alerts fire on drops in valid rate, speed or parser output.'],
  ], { widths: [0.4, 1.9, 6], boldFirst: true }),
  spacer(200),
  H2('6.2  Services and their scaling signal'),
  table(['Service', 'Runs on', 'Scales on', 'Start size (prod)'], [
    ['SERP Gateway (Search, Usage, Admin, Health)', 'ECS Fargate', 'CPU > 60% or requests per task', '2 tasks, 0.5 vCPU / 1 GB'],
    ['Browser workers', 'ECS on EC2 (c7i.xlarge)', 'Busy slots > 70% for 3 min', '2 tasks × 4 slots, one per AZ'],
    ['Event writer / rollups', 'ECS Fargate (scheduled)', 'Every 5 minutes', '1 task'],
    ['Canary', 'EventBridge → ECS task', 'Hourly', '1 task, 5 known queries'],
  ], { widths: [2.6, 2, 2.2, 2.2], boldFirst: true }),
  small('Start sizes are a first guess; the week-8 load test sets the real numbers.', { before: 80 }),

  H1(7, 'How one request flows'),
  ...figure('07_request_lifecycle', 'One request from start to finish, with the time budget for each stage', 6.5, 6.6),
  H2('7.1  Every answer is complete or an honest error', { pageBreak: true }),
  P('The checks run in this order. The first one that fails decides the error code, and nothing partial is ever returned.'),
  ...figure('08_outcomes', 'Outcome decision tree and error codes', 6.1, 6.9),
]));

// ---- 8 Database design (3 landscape figures) + rules (portrait)
S.push(portrait([
  H1(8, 'Database design', { pageBreak: false }),
  P('PostgreSQL holds accounts and keys, every request, the parsed results of valid pages, and usage. Page HTML and screenshots live in S3; the database only keeps their keys. The model is shown three ways: two conceptual ER diagrams (entities, attributes and relationships), then the physical tables.'),
  H2('8.1  Data rules'),
  table(['Rule', 'Why'], [
    ['Parsed rows are written only for status 200.', 'A failed page can never look like data. Failures keep the request row and its reason.'],
    ['`aio_sources.url` is NOT NULL.', 'The completeness rule lives in the database too: a source without a real link cannot be stored.'],
    ['`search_requests` is partitioned by month.', 'Fast queries on recent traffic and cheap retention: old partitions are detached, not deleted row by row.'],
    ['API keys are stored as an 8-character prefix + salted hash.', 'The key is shown once. A database leak does not leak working keys.'],
    ['Proxy credentials live only in Secrets Manager.', '`url_template` is stored masked. No secret ever sits in the database or a log line.'],
    ['`google_requests` keeps the breakdown as JSONB.', 'Page loads, `/async`, `/goto`, fallbacks, other Google and non-Google calls — `requests_used` can always be audited.'],
    ['`usage_daily` is rolled up from the event stream.', 'Billing and usage reports never scan raw request rows.'],
  ], { widths: [3.2, 5], boldFirst: false }),
  spacer(200),
  H2('8.2  Retention (proposed)'),
  table(['Data', 'Where', 'Kept for'], [
    ['Request rows', 'PostgreSQL', '13 months'],
    ['Parsed results', 'PostgreSQL', '90 days'],
    ['Page HTML + screenshots (proof)', 'Amazon S3', '14 days'],
    ['Request events', 'Amazon S3 (Parquet)', '13 months'],
    ['Daily usage', 'PostgreSQL', 'For the life of the contract'],
    ['Application logs', 'CloudWatch Logs', '30 days'],
  ], { widths: [3.4, 2.6, 2.4], boldFirst: true }),
  small('Retention periods are a proposal. The client confirms them in section 17.', { before: 80 }),
]));
S.push(landscape([
  H2('8.3  Conceptual model — search data'),
  ...figure('09_er_search_data', 'ER diagram: a search request, its pages and everything read from them', 9.5, 6.1),
]));
S.push(landscape([
  H2('8.4  Conceptual model — accounts, proxies and operations'),
  ...figure('10_er_operations', 'ER diagram: who sent the request, how it was served, and what it cost', 9.5, 6.1),
]));
S.push(landscape([
  H2('8.5  Physical schema'),
  ...figure('10b_physical_schema', 'PostgreSQL tables, keys and relationships', 9.5, 6.1),
]));

// ---- 9 API spec, 10 tech stack
S.push(portrait([
  H1(9, 'API specification', { pageBreak: false }),
  H2('9.1  Endpoints'),
  table(['Method', 'Path', 'Purpose', 'Auth', 'Status'], [
    ['POST', '`/serp`', 'Fetch and parse one Google results page (or more with `results` > 10)', 'X-API-Key', 'Built'],
    ['GET', '`/health`', 'Liveness check for the load balancer', 'None', 'Built'],
    ['GET', '`/v1/usage?from=&to=`', 'Daily usage for the calling key', 'X-API-Key', 'New'],
    ['POST / DELETE', '`/v1/keys`', 'Create or revoke keys, set quotas', 'Admin key', 'New'],
    ['POST', '`/v1/jobs`', 'Batch of searches with a webhook when done', 'X-API-Key', 'Phase 2'],
  ], { widths: [1.1, 2.1, 3.6, 1.2, 0.9] }),
  spacer(160),
  H2('9.2  Request body — POST /serp'),
  table(['Field', 'Type', 'Default', 'Rule'], [
    ['`url`', 'string', '—', '`google.com` or `www.google.com`, path `/search`, must have `q=`. Sent exactly as given. Anything else → 400 `invalid_url`, nothing fetched.'],
    ['`results`', 'int', '10', '10 = page 1 only. More adds pages with `&start=10`, `20`, … on a copy of the URL.'],
    ['`country`', 'string', 'US', 'Browser locale and proxy country only. Never changes the URL.'],
    ['`language`', 'string', 'en', 'Browser `Accept-Language` only. Never changes the URL.'],
    ['`return_json`', 'bool', 'true', '`false` returns page 1\'s rendered HTML as `text/html`.'],
  ], { widths: [1.3, 0.8, 0.8, 5.4] }),
  spacer(160),
  H2('9.3  Response — example'),
  codeBlock([
    '{',
    '  "status_code": 200, "requests_used": 9, "elapsed_time": 1840,',
    '  "results": [{',
    '    "page": 1,',
    '    "paid":    [ { "url": "...", "title": "...", "content": "...", "sub_links": [] } ],',
    '    "organic": [ { "url": "https://...", "title": "...", "content": "...",',
    '                   "sub_links": [ { "title": "...", "url": "https://..." } ] } ],',
    '    "ai_overview": {',
    '      "intro":    [ "..." ],',
    '      "sections": [ { "title": "...", "text": "- ...\\n- ..." } ],',
    '      "sources":  [ { "title": "...", "url": "https://...", "snippet": "..." } ]',
    '    },',
    '    "knowledge_panel": null, "number_of_results": 129000000,',
    '    "suggestions": [ "..." ], "corrections": []',
    '  }],',
    '  "error": null, "error_message": null',
    '}',
  ]),
  small('Values are illustrative. On any error `results` is `[]` and `error` / `error_message` explain why.', { before: 80 }),
  H2('9.4  Status and error codes', { pageBreak: true }),
  table(['HTTP', '`error`', 'When'], [
    ['200', '`null`', 'Valid result: every field read in full.'],
    ['400', '`invalid_url`', 'URL not allowed, or a malformed request body. Nothing is fetched.'],
    ['429', '`blocked_captcha`', 'Google CAPTCHA or "unusual traffic" page (`/sorry/`).'],
    ['502', '`consent_wall`', '"Before you continue" consent page.'],
    ['502', '`degraded_page`', 'JavaScript notice, basic-HTML page, no results container, or zero organic results.'],
    ['502', '`aio_incomplete`', 'AI Overview did not finish loading or expanding, Google shows its "can\'t generate" message, or a source has no real link.'],
    ['502', '`parse_error`', 'Parsing crashed, or a result link\'s destination could not be resolved.'],
    ['502', '`network_error`', 'Browser or network failure.'],
    ['504', '`timeout`', 'Navigation or the whole-request deadline ran out.'],
  ], { widths: [0.7, 1.9, 5.8], boldFirst: true }),
  spacer(160),
  H2('9.5  Debug headers (never in the JSON body)'),
  table(['Header', 'Contents'], [
    ['`X-Request-Id`', 'ID to quote when asking about a request; also the key of its saved proof.'],
    ['`X-Classification`', 'How the page was judged (ok, blocked, consent, degraded, …).'],
    ['`X-AIO-State`', '`absent`, `complete` or `incomplete`.'],
    ['`X-Timings`', 'Stage times (`nav_ms`, `results_ms`, `aio_ms`, `links_ms`, `total_ms`), links needed/resolved, bytes in.'],
    ['`X-Google-Requests`', '`requests_used` plus every request by kind: document, async, goto, goto_fallback, other_google, non_google.'],
    ['`X-Proxy-Session`', 'Proxy session id, exit IP before and after, whether the IP changed.'],
  ], { widths: [2.2, 6.2] }),

  H1(10, 'Tech stack'),
  P('Green chips are already in the code and covered by tests. Blue chips are added for production.'),
  ...figure('11_tech_stack', 'Tech stack by layer', 6.2, 4.1),
  table(['Choice', 'Why this one'], [
    ['Python 3.12 + FastAPI', 'The engine is already written and tested in it. Pydantic enforces the client\'s exact schema.'],
    ['Playwright + headless shell', 'A real browser plus DevTools access to count bytes and read redirects. Makes no requests of its own.'],
    ['selectolax', 'A few milliseconds per page, so parsing never threatens the time budget.'],
    ['Redis Streams', 'Sub-5 ms hand-off to workers, fair work sharing, no extra broker to run.'],
    ['PostgreSQL 16', 'Relational core for keys, requests and usage; JSONB for nested parts; partitions for volume.'],
    ['ECS (Fargate + EC2)', 'Fargate keeps the API simple; EC2 gives Chromium steady CPU for less. Two services do not need Kubernetes.'],
    ['Terraform + GitHub Actions', 'Every environment is rebuilt from code and every change is reviewed in a pull request.'],
    ['OpenTelemetry + Grafana', 'Vendor-neutral. Valid rate and P95 are dashboard panels, not log searches.'],
    ['AWS us-east-1', 'A US region near Google\'s US front ends. Confirm against the proxy provider\'s gateway location.'],
  ], { widths: [2.6, 6], boldFirst: true }),
]));

// ---- 11 Infrastructure (landscape) + environments (portrait)
S.push(landscape([
  LH1(11, 'Infrastructure and deployment'),
  ...figure('12_deployment', 'AWS deployment across two availability zones, with the delivery pipeline', 9.5, 6.05),
]));
S.push(portrait([
  H2('11.1  Environments'),
  table(['Environment', 'Used for', 'Size', 'Talks to Google?'], [
    ['Development', 'Engineers; saved-page fixtures and the local Google stand-in', '1 API task, 1 worker (2 slots)', 'No'],
    ['Staging', 'Smoke tests, canary, release checks through the proxy', '1 API task, 1 worker (4 slots)', 'Yes, paced and capped'],
    ['Production', 'Client traffic', '2+ API tasks, 2+ workers over 2 AZs', 'Yes'],
  ], { widths: [1.5, 3.4, 2.4, 1.6], boldFirst: true }),
  spacer(200),
  H2('11.2  Capacity planning'),
  P('Slots needed = peak searches per second × seconds per page × 1.5 headroom. The table assumes 3 seconds per page and a peak of 3× the daily average. Both get replaced by measured values after the smoke test.'),
  table(['Daily searches', 'Average / s', 'Peak / s', 'Busy slots (with headroom)', 'Worker tasks (4 slots each)'], [
    ['50,000', '0.6', '1.7', '8', '2'],
    ['250,000', '2.9', '8.7', '39', '10'],
    ['1,000,000', '11.6', '34.7', '156', '39'],
  ], { widths: [1.6, 1.3, 1.3, 2.2, 2.2], align: [AlignmentType.LEFT, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER], boldFirst: true }),
  small('Proxy traffic per page is not known yet; it is the first thing the smoke test measures. Proxy cost = pages × measured MB per page × provider price.', { before: 80 }),
  spacer(120),
  H2('11.3  Release flow'),
  ...bullets([
    'Every pull request runs the 183 tests, including the 16 real Google pages and the local Google stand-in. Nothing reaches staging if a parser test fails.',
    'Images are built once, scanned and pushed to ECR, then promoted unchanged from staging to production.',
    'ECS deploys blue/green. If the error rate or health checks slip, it rolls back on its own.',
    'A parser fix (Google changed its page) is a normal release: saved failing page → new fixture → fix → same-day deploy.',
  ]),

  H1(12, 'Non-functional requirements'),
  table(['Area', 'Requirement', 'Target'], [
    ['Performance', 'End-to-end P95 per corpus, measured by the client, failures included', '≤ 2,000 ms'],
    ['Reliability', 'Valid-result rate per corpus', '≥ 98%'],
    ['Completeness', 'Returned items with every field read in full', '100% (else error)'],
    ['Availability', 'API reachable and answering (gateway + health)', '99.9% monthly'],
    ['Scalability', 'Capacity grows by adding worker slots', 'Config only'],
    ['Transparency', 'Every Google request counted and broken down by kind', '100%'],
    ['Cost control', 'Proxy bytes per page measured and reported; test runs stop before budget', 'Every request'],
    ['Traceability', 'Every failure has a request ID, a reason and a saved page', '100%'],
    ['Recovery', 'Data loss window / time to restore', 'RPO ≤ 5 min, RTO ≤ 1 h'],
    ['Maintainability', 'Google layout change → tested fix in production', 'Same working day'],
  ], { widths: [1.6, 5, 1.8], boldFirst: true }),

  spacer(200),
  H1(13, 'Security and compliance', { pageBreak: false }),
  table(['Area', 'What we do'], [
    ['Transport', 'TLS 1.2+ only, HSTS on the API domain.'],
    ['Authentication', 'API keys: 8-character prefix + salted hash; shown once. Per-key rate limit and quota. Admin API needs a separate key and an IP allow-list.'],
    ['Secrets', 'Proxy credentials in AWS Secrets Manager (KMS-encrypted). Masked in every log line (`http://use***@host:port`).'],
    ['Network', 'Only the load balancer is public. Workers and data sit in private subnets; workers leave through NAT to the proxy provider only.'],
    ['Data', 'No personal data is collected. Search terms in URLs are treated as client-confidential. Encryption at rest for RDS, Redis and S3.'],
    ['Access', 'Least-privilege IAM roles per service, SSO for engineers, CloudTrail audit log.'],
    ['Responsible use', 'No CAPTCHA solving, no stealth or fingerprint spoofing, pacing and traffic budgets in every test tool.'],
  ], { widths: [1.8, 6.6], boldFirst: true }),
  spacer(160),
  callout('For the client\'s legal review', [
    'Google\'s terms of service restrict automated access to its search results. The platform avoids evasion techniques on purpose, but the decision to collect this data, and at what volume, sits with the client and their legal advisers.',
  ], { fill: 'FFFBEB', edge: 'D97706', titleColor: '92400E' }),

  H1(14, 'Monitoring and alerting'),
  P('Two numbers run the service: the valid-result rate and P95. Everything else explains why one of them moved.'),
  table(['Signal', 'Alert when', 'First action'], [
    ['Valid-result rate (15 min)', 'Below 98%', 'Look at the top failure reason and its saved pages.'],
    ['P95 latency (15 min)', 'Above 2,000 ms', 'Check stage timings (`X-Timings`) to see which stage grew.'],
    ['`blocked_captcha` share', 'Above 2%, or a spike on one exit IP', 'Rest that proxy or provider; confirm sessions rotate.'],
    ['`aio_incomplete` share', 'Doubles against the 7-day baseline', 'Check AI Overview wait settings against the canary pages.'],
    ['Canary field drift', 'A field that used to be filled comes back empty', 'Parser fix from the saved page, same day.'],
    ['Proxy bytes per page', '30% above baseline', 'Check what the page started loading; tighten blocking.'],
    ['Busy worker slots', 'Above 80% for 10 minutes', 'Autoscaling should already be adding workers; page on-call if not.'],
    ['Gateway 5xx (own errors)', 'Above 0.5%', 'Roll back the last release if it lines up.'],
  ], { widths: [2.3, 2.5, 3.6], boldFirst: true }),
  small('Thresholds are starting points and will be tuned on real traffic.', { before: 80 }),

  H1(15, 'Delivery plan'),
  ...figure('13_roadmap', 'Twelve-week plan from smoke test to go-live and hypercare', 6.6, 4.6),
  table(['Milestone', 'When', 'Done when'], [
    ['M1  Smoke test report', 'End of W1', 'Up to 23 page loads through the client\'s proxy. The report shows traffic per page, block rate, AI Overview timing, and every query that did not run.'],
    ['M2  Targets met on the benchmark', 'End of W3', 'Mixed and difficult corpora at ≥ 98% valid and P95 ≤ 2 s — or a written gap analysis with options and costs.'],
    ['M3  Staging ready', 'End of W7', 'The full platform built from Terraform in staging; canary green for 3 days in a row.'],
    ['M4  Acceptance sign-off', 'End of W9', 'Load test at the agreed volume passes; the client signs acceptance.'],
    ['Go-live', 'End of W10', 'Production traffic on, followed by two weeks of daily failure reviews.'],
  ], { widths: [2.3, 1.2, 5], boldFirst: true }),

  H1(16, 'Risks and mitigations'),
  table(['Risk', 'Impact', 'Likelihood', 'Mitigation'], [
    ['Google blocks proxy traffic at scale', lvl('High'), lvl('Medium'), 'Health scores, fresh sessions after a block, block rate per exit IP, a second provider on standby.'],
    ['AI Overview pushes P95 over 2 s', lvl('High'), lvl('High'), 'Early "no AI Overview coming" exit, tuned waits. If still over, agree a separate P95 for AI Overview queries — completeness is not traded for speed.'],
    ['Google changes the page layout', lvl('High'), lvl('Medium'), 'Hourly canary, 16-page fixture suite, same-day fix from the saved page.'],
    ['`/goto` lookups change or get limited', lvl('High'), lvl('Medium'), 'In-page lookup with a fallback client; alert on unresolved links; never guess a URL.'],
    ['Proxy bandwidth costs more than planned', lvl('Medium'), lvl('Medium'), 'Bytes measured per page, cache-safe resource blocking, hard budgets on test runs.'],
    ['Proxy provider outage', lvl('Medium'), lvl('Low'), 'Provider switch is config only (`static` / `list`); keep a second contract ready.'],
    ['Terms-of-service exposure', lvl('High'), 'Client to assess', 'No evasion techniques; pacing; client legal review before scaling up.'],
  ], { widths: [2.5, 0.9, 1.1, 4.1] }),

  spacer(200),
  H1(17, 'Open decisions for the client', { pageBreak: false }),
  P('We need an answer on these before acceptance. Each has our recommendation so a "yes" is enough.'),
  table(['#', 'Question', 'Our recommendation'], [
    ['1', 'A result link whose destination cannot be resolved: keep `parse_error`, or add a new `incomplete_result` code?', 'Keep `parse_error` now; add the new code in v1.1 if your tooling needs to tell them apart.'],
    ['2', 'With `results` > 10, page 1 succeeds but page 2 is blocked: return an error for all, or the good pages plus a flag?', 'Return the error (current behaviour), matching "results: [] on error".'],
    ['3', 'Google shows "Can\'t generate an AI Overview right now": failure or no AI Overview?', 'Failure (`aio_incomplete`), because the page is not what a user normally sees.'],
    ['4', 'Bold-labelled groups inside AI Overview lists: separate sections or lines inside their section?', 'Lines inside their section (`- Label: text`), as built.'],
    ['5', 'Malformed request body: 400 `invalid_url`?', 'Yes, it is the closest agreed code.'],
    ['6', 'Mid-page "in-feed" ads: include in `paid`?', 'No, `paid` stays top and bottom blocks as the brief defines.'],
    ['7', 'A separate P95 target for queries with an AI Overview?', 'Decide after the smoke test shows real AI Overview timings.'],
    ['8', 'Retention periods in section 8.2.', 'Accept as proposed.'],
    ['9', 'Expected daily volume at launch and in 12 months.', 'Needed to size workers and proxy spend (section 11.2).'],
  ], { widths: [0.4, 4.3, 3.7], boldFirst: true }),

  H1(18, 'Glossary'),
  table(['Term', 'Meaning'], [
    ['SERP', 'Search Engine Results Page — the page Google shows after a search.'],
    ['AI Overview', 'The AI-written summary Google shows above the results, with links to its sources.'],
    ['Organic result', 'A normal, unpaid search result.'],
    ['Knowledge panel', 'The fact box on the right side for people, places and things.'],
    ['CAPTCHA', 'Google\'s "prove you are human" check. We never try to solve it.'],
    ['Residential proxy', 'A connection that leaves from a normal home internet address instead of a data centre.'],
    ['Sticky session', 'Keeping the same proxy exit IP for all requests that belong to one page.'],
    ['`/goto` link', 'Google\'s wrapper around result links since 26 Aug 2026. We ask Google where it points instead of guessing.'],
    ['P95', '95% of requests are faster than this number.'],
    ['Valid result', 'A 200 response where every returned field was read in full.'],
    ['Canary', 'A small set of known searches run on a schedule to catch problems before clients do.'],
    ['Fixture', 'A saved real Google page used in automated tests.'],
    ['Headless shell', 'Chromium without a window, used for automation. Unlike the full browser, it makes no calls to Google on its own.'],
    ['CDP', 'Chrome DevTools Protocol — how the worker counts bytes and reads redirects inside the browser.'],
  ], { widths: [1.8, 6.6], boldFirst: true }),
]));

// List of figures goes where the contents section left a slot for it.
{
  const kids = S[1].children, i = kids.findIndex((k) => k && k.lofSlot);
  const lof = [new Paragraph({ children: [new TextRun({ text: 'Figures', bold: true, size: 26, color: '1D5F82', font: FONT })], spacing: { before: 120, after: 100 } })];
  for (const [n, cap] of figList) {
    lof.push(new Paragraph({ spacing: { after: 40 }, tabStops: [{ type: TabStopType.LEFT, position: 1000 }, { type: TabStopType.RIGHT, position: P_BODY, leader: 'dot' }],
      children: [
        new TextRun({ text: `Figure ${n}`, bold: true, color: NAVY, size: 18, font: FONT }),
        new TextRun({ text: `\t${cap}`, color: INK, size: 18, font: FONT }),
        new TextRun({ text: `\t${PAGES['fig' + n] || '00'}`, color: MUTED, size: 18, font: FONT }),
      ] }));
  }
  kids.splice(i, 1, ...lof);
}

// ------------------------------------------------------------------- styles
const doc = new Document({
  creator: 'Devfusion Engineering', title: 'Google SERP API — Business Requirements & Technical Specification', description: 'BRD and technical specification v1.0',
  styles: {
    default: { document: { run: { font: FONT, size: 21, color: INK } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 40, bold: true, color: NAVY, font: FONT },
        paragraph: { spacing: { before: 0, after: 200 }, outlineLevel: 0, border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: 'E2E8F0', space: 6 } } } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 26, bold: true, color: '1D5F82', font: FONT }, paragraph: { spacing: { before: 200, after: 110 }, outlineLevel: 1 } },
      { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 22, bold: true, color: INK, font: FONT }, paragraph: { spacing: { before: 160, after: 90 }, outlineLevel: 2 } },
    ],
  },
  numbering: { config: [
    { reference: 'dots', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 360, hanging: 240 } }, run: { color: TEAL, bold: true } } }] },
    { reference: 'cell', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 220, hanging: 180 } }, run: { color: TEAL, bold: true } } }] },
  ] },
  sections: S,
});

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(OUT, buf); console.log('wrote', OUT, 'figures:', figNo); });
