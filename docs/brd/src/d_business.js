// Business-facing visuals: cover, pain points, solution architecture, status.
const L = require('./lib');
const { C, text, rect, box, icon, line, pill } = L;

const D = {};

// ---------------------------------------------------------------- pain points
D.painpoints = async () => {
  const W = 1000, rows = [
    ['shield-alert', 'Google blocks automated traffic', 'A data-centre or home IP often gets a CAPTCHA\non its very first request. That result is lost.',
      'US residential proxies, one sticky session per browser', 'A blocked session is dropped and never retried on the same IP.\nEvery exit IP gets a health score; weak ones are rested.', 'Tracked: block rate per proxy'],
    ['timer', 'Answers take too long', 'AI Overviews stream in after the page loads.\nA full one can take several seconds.',
      'Warm browsers and a time budget for each stage', 'Browsers stay open between requests, plain queries return as\nsoon as results show, links are resolved 16 at a time.', 'Target: P95 ≤ 2.0 s'],
    ['file-warning', 'Partial or guessed data', 'A half-loaded AI Overview or a link rebuilt from\nthe breadcrumb looks fine, but it is wrong.',
      'A completeness check before every answer', 'If any part of the page could not be read in full, you get a\nclear error code. Never a partial result dressed up as valid.', 'Target: 0 made-up fields'],
    ['scan-search', 'Google keeps changing the page', 'On 26 Aug 2026 result links moved behind\nencrypted /goto redirects overnight.',
      'Versioned parsers, real-page tests, hourly canary', '16 saved Google pages are tested on every build. Live canary\nqueries raise an alert when a field starts coming back empty.', 'Target: drift caught within 1 hour'],
    ['coins', 'Proxy bandwidth bills add up', 'Residential proxies charge per GB and every\npage is a full browser load.',
      'Download only what the data needs', 'Images, fonts and media are skipped, bytes are counted per\npage, and test runs stop before they pass a set budget.', 'Reported: KB per page and per run'],
    ['eye-off', 'No clear view of usage and cost', 'Hard to say how many Google requests a single\nsearch really costs.',
      'Every Google request is counted and reported', 'Page loads, AI Overview follow-ups and link lookups all count\nin requests_used, rolled up per API key per day.', 'Target: 100% of requests counted'],
    ['server-crash', 'Stuck on one machine', 'One process with one browser cannot carry a\nreal production workload.',
      'Stateless API plus a browser fleet that scales itself', 'Workers are added when busy slots climb and removed when\nidle. No single server can take the service down.', 'Scales out with config, not code'],
  ];
  const top = 70, rh = 118, gap = 14;
  const H = top + rows.length * (rh + gap) + 6;
  let s = '';
  s += text(24, 36, 'WHAT HURTS TODAY', { size: 13, weight: 700, fill: C.red, ls: 1.2 });
  s += text(452, 36, 'WHAT THE PLATFORM DOES ABOUT IT', { size: 13, weight: 700, fill: C.green, ls: 1.2 });
  s += `<line x1="24" y1="50" x2="392" y2="50" stroke="${C.redLine}" stroke-width="2"/>`;
  s += `<line x1="452" y1="50" x2="976" y2="50" stroke="${C.greenLine}" stroke-width="2"/>`;
  rows.forEach((r, i) => {
    const y = top + i * (rh + gap);
    // pain card
    s += rect(20, y, 376, rh, { fill: '#FFF7F2', stroke: '#FAD7C3', r: 12 });
    s += `<circle cx="54" cy="${y + 36}" r="20" fill="${C.redSoft}"/>` + icon(r[0], 43, y + 25, 22, C.red);
    s += text(86, y + 32, r[1], { size: 15.5, weight: 700, fill: C.ink });
    s += text(86, y + 56, r[2], { size: 12.5, fill: '#57534E', lh: 17 });
    // connector
    s += `<circle cx="424" cy="${y + rh / 2}" r="15" fill="${C.navy}"/>` + icon('arrow-right', 414, y + rh / 2 - 10, 20, '#fff', 2.5);
    // fix card
    s += rect(452, y, 528, rh, { fill: '#F3FBF6', stroke: '#BFE8CF', r: 12 });
    s += `<circle cx="486" cy="${y + 36}" r="20" fill="${C.greenSoft}"/>` + icon('check', 475, y + 25, 22, C.green, 2.6);
    s += text(518, y + 32, r[3], { size: 15.5, weight: 700, fill: C.ink });
    s += text(518, y + 54, r[4], { size: 12.5, fill: '#44524A', lh: 17 });
    s += pill(518, y + rh - 34, r[5], { fill: C.white, stroke: '#9FD9B5', color: C.green, size: 12, weight: 600, h: 24, icon: 'target' });
  });
  await L.render('02_pain_points', W, H, s);
};

// ------------------------------------------------------- solution architecture
D.solution = async () => {
  const W = 1000, H = 764;
  let s = '';
  // Left: who asks
  s += text(20, 34, 'WHO USES IT', { size: 12, weight: 700, fill: C.muted, ls: 1.2 });
  const users = [['laptop', 'Your apps &\nSEO tools'], ['chart-column', 'Dashboards\n& reports'], ['database', 'Data team\npipelines'], ['gauge', 'Benchmark\nruns']];
  users.forEach((u, i) => {
    s += box(20, 52 + i * 82, 172, 66, u[1], { fill: C.white, stroke: C.line, r: 10, icon: u[0], iconPos: 'left', size: 13.5, iconColor: C.blue, shadow: true });
  });
  s += line([[198, 222], [248, 222]], { end: true, color: C.navy, width: 2.5 });
  s += text(222, 208, 'search link', { size: 11, fill: C.muted, anchor: 'middle' });

  // Platform box
  const px = 256, py = 40, pw = 500, ph = 452;
  s += rect(px, py, pw, ph, { fill: '#F4F8FC', stroke: C.blue, sw: 2, r: 16 });
  s += rect(px, py, pw, 44, { fill: C.blue, r: 16 });
  s += rect(px, py + 24, pw, 20, { fill: C.blue, r: 0 });
  s += icon('search', px + 16, py + 11, 22, '#fff', 2.2);
  s += text(px + 48, py + 29, 'SERP API platform', { size: 17, weight: 700, fill: '#fff' });
  s += text(px + pw - 16, py + 29, 'runs on AWS', { size: 12, fill: '#DCEAF5', anchor: 'end' });

  const steps = [
    ['key-round', 'Check the request', 'Is it a real Google search link? Is the API key\nknown and still inside its quota?'],
    ['globe', 'Open the page like a real US visitor', 'A real Chrome browser, through a US home\ninternet connection. No CAPTCHA tricks.'],
    ['scan-text', 'Read every part of the page', 'Ads, results, the full AI Overview with every\nsource, knowledge panel, related searches.'],
    ['shield-check', 'Check that nothing is missing', 'If anything could not be read in full, you get a\nclear error, never a half answer.'],
  ];
  steps.forEach((st, i) => {
    const y = py + 60 + i * 97;
    s += rect(px + 18, y, pw - 36, 84, { fill: C.white, stroke: '#C9DCEC', r: 12, shadow: true });
    s += `<circle cx="${px + 54}" cy="${y + 42}" r="22" fill="${C.lightBlue}"/>` + icon(st[0], px + 43, y + 31, 22, C.blueDark);
    s += text(px + 92, y + 30, `${i + 1}. ${st[1]}`, { size: 15, weight: 700 });
    s += text(px + 92, y + 51, st[2], { size: 12.5, fill: C.muted, lh: 17 });
    if (i < steps.length - 1) s += line([[px + 54, y + 84], [px + 54, y + 97]], { color: C.blue, width: 2 });
  });

  // Outside helpers under the platform
  const hy = py + ph + 42;
  s += box(px + 10, hy, 150, 66, 'US residential\nproxy network', { fill: C.purpleSoft, stroke: '#C4B5FD', r: 10, size: 13, color: C.purple });
  s += box(px + 196, hy, 140, 66, 'Google\nSearch', { fill: C.white, stroke: C.line, r: 10, size: 13.5, icon: 'globe', iconPos: 'left', iconColor: C.blue });
  s += line([[px + 85, py + ph], [px + 85, hy]], { start: true, end: true, color: C.purple, width: 2 });
  s += line([[px + 160, hy + 33], [px + 196, hy + 33]], { start: true, end: true, color: C.purple, width: 2, head: 8 });
  s += box(px + 356, hy, 144, 66, 'Proof saved', { fill: C.amberSoft, stroke: '#FCD34D', r: 10, size: 13, color: C.amber, sub: 'HTML + screenshot', subColor: '#92400E', subSize: 11.5 });
  s += line([[px + 428, py + ph], [px + 428, hy]], { end: true, color: C.amber, width: 2 });

  // arrow out
  s += line([[px + pw + 4, 222], [px + pw + 40, 222]], { end: true, color: C.navy, width: 2.5 });
  s += text(px + pw + 22, 208, 'JSON', { size: 11, fill: C.muted, anchor: 'middle' });

  // Right: what you get
  const rx = 802, rw = 184;
  s += text(rx, 34, 'WHAT YOU GET', { size: 12, weight: 700, fill: C.muted, ls: 1.2 });
  s += rect(rx, 52, rw, 340, { fill: C.white, stroke: C.line, r: 12, shadow: true });
  const outs = [['megaphone', 'Paid ads'], ['list', 'Organic results'], ['sparkles', 'AI Overview'], ['link', 'AI Overview sources'], ['book-open', 'Knowledge panel'], ['hash', 'Result count'], ['messages-square', 'Related searches'], ['spell-check', 'Spelling fixes']];
  outs.forEach((o, i) => {
    s += icon(o[0], rx + 14, 70 + i * 39, 18, C.teal, 2);
    s += text(rx + 42, 84 + i * 39, o[1], { size: 13.5, weight: 500 });
  });
  s += box(rx, 406, rw, 66, 'Or a clear error', { fill: C.redSoft, stroke: C.redLine, r: 12, size: 14, color: C.red, sub: 'with a reason code', subColor: '#9A3412', subSize: 12 });

  // Promise band
  const by = 628;
  s += rect(20, by, 960, 120, { fill: C.navy, r: 14 });
  s += text(40, by + 32, 'WHAT WE PROMISE', { size: 12, weight: 700, fill: '#93C5FD', ls: 1.2 });
  const prom = [['ban', 'No made-up data', 'Missing means null'], ['shield-off', 'No CAPTCHA tricks', 'Blocked means we say so'], ['calculator', 'Every request counted', 'Shown in requests_used'], ['file-search', 'Proof kept', 'HTML + screenshot'], ['plug-zap', 'No third-party data', 'No SERP feeds or caches']];
  prom.forEach((p, i) => {
    const x = 36 + i * 187;
    s += icon(p[0], x, by + 55, 24, '#7DD3FC', 2);
    s += text(x + 34, by + 68, p[1], { size: 13.5, weight: 700, fill: '#fff' });
    s += text(x + 34, by + 88, p[2], { size: 12, fill: '#BFD3E6' });
  });
  await L.render('04_solution_architecture', W, H, s);
};

// ----------------------------------------------------------------------- cover
D.cover = async () => {
  const W = 816, H = 1056;
  let s = '';
  s += `<defs><linearGradient id="cg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0B1E33"/><stop offset="1" stop-color="#153D5E"/></linearGradient>
  <linearGradient id="fade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0.10"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient></defs>`;
  s += `<rect width="${W}" height="${H}" fill="url(#cg)"/>`;
  // dotted texture
  for (let yy = 30; yy < 640; yy += 26) for (let xx = 30; xx < W; xx += 26) s += `<circle cx="${xx}" cy="${yy}" r="1" fill="#fff" opacity="0.07"/>`;
  // brand row
  s += `<rect x="64" y="64" width="34" height="34" rx="8" fill="${C.teal}"/>` + icon('search', 71, 71, 20, '#fff', 2.6);
  s += text(110, 87, 'DEVFUSION', { size: 15, weight: 700, fill: '#fff', ls: 3 });
  s += text(W - 64, 87, 'CONFIDENTIAL', { size: 11, weight: 600, fill: '#8FB3D1', ls: 2, anchor: 'end' });

  // illustration: SERP page -> engine -> JSON
  const iy = 170;
  // page mock
  s += rect(64, iy, 230, 290, { fill: '#fff', r: 10, opacity: 0.97 });
  s += rect(64, iy, 230, 30, { fill: '#E2E8F0', r: 10 }) + rect(64, iy + 18, 230, 12, { fill: '#E2E8F0', r: 0 });
  ['#F87171', '#FBBF24', '#34D399'].forEach((c, i) => { s += `<circle cx="${80 + i * 14}" cy="${iy + 15}" r="4" fill="${c}"/>`; });
  s += rect(80, iy + 42, 198, 16, { fill: '#F1F5F9', r: 8 });
  s += icon('search', 84, iy + 44, 12, '#64748B', 2.5);
  // AI overview block
  s += rect(80, iy + 70, 198, 62, { fill: '#EEF6FF', r: 6 });
  s += icon('sparkles', 88, iy + 77, 12, C.blue, 2.4) + text(104, iy + 87, 'AI Overview', { size: 10, weight: 700, fill: C.blueDark });
  [0, 1, 2].forEach((k) => { s += rect(88, iy + 96 + k * 10, 180 - k * 40, 5, { fill: '#BFDBFE', r: 2.5 }); });
  // results
  for (let k = 0; k < 4; k++) {
    const yy = iy + 146 + k * 34;
    s += rect(80, yy, 120 - (k % 2) * 20, 7, { fill: '#93C5FD', r: 3.5 });
    s += rect(80, yy + 12, 190, 5, { fill: '#E2E8F0', r: 2.5 });
    s += rect(80, yy + 21, 150, 5, { fill: '#E2E8F0', r: 2.5 });
  }
  // flow arrow and engine
  s += line([[306, iy + 145], [362, iy + 145]], { end: true, color: '#7DD3FC', width: 3, head: 12 });
  s += `<circle cx="408" cy="${iy + 145}" r="44" fill="none" stroke="#7DD3FC" stroke-width="2" stroke-dasharray="4 6"/>`;
  s += `<circle cx="408" cy="${iy + 145}" r="32" fill="${C.teal}"/>` + icon('cpu', 392, iy + 129, 32, '#fff', 2);
  s += line([[454, iy + 145], [510, iy + 145]], { end: true, color: '#7DD3FC', width: 3, head: 12 });
  // JSON card
  s += rect(522, iy, 230, 290, { fill: '#0A1929', stroke: '#2B4A66', sw: 1.5, r: 10 });
  const js = [['{', '#E2E8F0'], ['  "status_code": 200,', '#7DD3FC'], ['  "requests_used": 9,', '#7DD3FC'], ['  "results": [{', '#E2E8F0'], ['    "paid": [ … ],', '#A7F3D0'], ['    "organic": [ … ],', '#A7F3D0'], ['    "ai_overview": {', '#A7F3D0'], ['      "sections": [ … ],', '#FDE68A'], ['      "sources": [ … ]', '#FDE68A'], ['    },', '#E2E8F0'], ['    "knowledge_panel": {…}', '#A7F3D0'], ['  }],', '#E2E8F0'], ['  "error": null', '#7DD3FC'], ['}', '#E2E8F0']];
  js.forEach((l, i) => { s += text(538, iy + 28 + i * 18.5, l[0], { size: 11.5, fill: l[1], family: 'DejaVu Sans Mono, monospace', pre: true }); });

  // Title block
  s += text(64, 560, 'BUSINESS REQUIREMENTS & TECHNICAL SPECIFICATION', { size: 13, weight: 700, fill: '#7DD3FC', ls: 1.6 });
  s += text(62, 628, 'Google SERP API', { size: 58, weight: 800, fill: '#fff', family: 'Inter Display, Inter' });
  s += text(64, 672, 'Live Google results, AI Overviews and sources as clean JSON —', { size: 18, fill: '#C7D7E6' });
  s += text(64, 698, 'built to be fast, complete and honest about every failure.', { size: 18, fill: '#C7D7E6' });
  const chips = ['Pain points & goals', 'Solution architecture', 'System & backend design', 'Database schema', 'Tech stack', 'Delivery plan'];
  s += L.pillRow(64, 730, chips, { maxW: W - 128, gap: 8, lgap: 10, fill: 'none', stroke: '#3B6A8F', color: '#D6E4F0', size: 12.5, h: 28, pad: 14 });

  // meta panel
  const my = 880;
  s += `<rect x="0" y="${my}" width="${W}" height="${H - my}" fill="#fff"/>`;
  s += `<rect x="0" y="${my}" width="${W}" height="5" fill="${C.teal}"/>`;
  const meta = [['VERSION', '1.0'], ['DATE', '30 September 2026'], ['STATUS', 'Draft for client review'], ['PREPARED BY', 'Devfusion Engineering']];
  meta.forEach((m, i) => {
    const x = 64 + i * 176;
    s += text(x, my + 58, m[0], { size: 10.5, weight: 700, fill: C.muted, ls: 1.4 });
    s += text(x, my + 84, m[1], { size: 15, weight: 600, fill: C.navy });
  });
  s += text(64, my + 140, 'This document describes the target platform. Figures marked "target" are goals to be proven by the benchmark, not measurements.', { size: 11, fill: C.muted });
  await L.render('00_cover', W, H, s, { scale: 3 });
};

module.exports = D;

if (require.main === module) {
  (async () => {
    const names = process.argv.slice(2);
    for (const n of names.length ? names : Object.keys(D)) await D[n]();
    await L.done();
  })();
}
