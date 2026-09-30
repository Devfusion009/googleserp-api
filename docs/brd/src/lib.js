// Shared drawing helpers for the BRD diagrams.
// Every diagram is plain SVG rendered to PNG by headless Chromium (render()).
const fs = require('fs');
const path = require('path');

const ICON_DIR = path.join(path.dirname(require.resolve('lucide-static/package.json')), 'icons');
const OUT_DIR = path.join(__dirname, '..', 'images');

// One palette for the document and every diagram.
const C = {
  navy: '#0F2A44', ink: '#1E293B', muted: '#64748B', faint: '#94A3B8', line: '#CBD5E1',
  soft: '#F1F5F9', softer: '#F8FAFC', white: '#FFFFFF',
  blue: '#2F86B0', blueDark: '#1D5F82', lightBlue: '#D4E6F5', lightBlueStroke: '#4F7597',
  teal: '#14B39A', tealDark: '#0E8C78', tealSoft: '#D5F5EF',
  slate: '#5E6E8C', coral: '#EE9A95', coralStroke: '#A94442',
  green: '#15803D', greenSoft: '#DCFCE7', greenLine: '#86EFAC',
  red: '#C2410C', redSoft: '#FFEDD5', redLine: '#FDBA74',
  rose: '#BE123C', roseSoft: '#FFE4E6',
  amber: '#B45309', amberSoft: '#FEF3C7',
  purple: '#6D28D9', purpleSoft: '#EDE9FE',
  weak: '#E6EDB7', weakStroke: '#A3B04F', multi: '#FFD0D8', multiStroke: '#E07A8E',
  isa: '#FBE7E3', isaStroke: '#D98F80',
};

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function icon(name, x, y, size, color, sw = 2) {
  const raw = fs.readFileSync(path.join(ICON_DIR, name + '.svg'), 'utf8');
  const inner = raw.slice(raw.indexOf('>', raw.indexOf('<svg')) + 1, raw.lastIndexOf('</svg>'));
  return `<svg x="${x}" y="${y}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;
}

// Multi-line text. `str` may contain \n. y is the baseline of the first line
// unless valign:'middle' (then the block is centred on y).
function text(x, y, str, o = {}) {
  const size = o.size || 14, lh = o.lh || Math.round(size * 1.3);
  const lines = String(str).split('\n');
  let y0 = y;
  if (o.valign === 'middle') y0 = y - ((lines.length - 1) * lh) / 2 + size * 0.35;
  const attrs = [
    `font-size="${size}"`, `font-weight="${o.weight || 400}"`, `fill="${o.fill || C.ink}"`,
    `text-anchor="${o.anchor || 'start'}"`,
    o.family ? `font-family="${o.family}"` : '',
    o.style ? `font-style="${o.style}"` : '',
    o.ls ? `letter-spacing="${o.ls}"` : '',
    o.deco ? `text-decoration="${o.deco}"` : '',
    o.cls ? `class="${o.cls}"` : '',
    o.pre ? 'xml:space="preserve" style="white-space:pre"' : '',
  ].join(' ');
  return lines.map((l, i) => `<text x="${x}" y="${y0 + i * lh}" ${attrs}>${esc(l)}</text>`).join('');
}

function rect(x, y, w, h, o = {}) {
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${o.r ?? 8}" fill="${o.fill || C.white}" stroke="${o.stroke || 'none'}" stroke-width="${o.sw || 1.5}" ${o.dash ? `stroke-dasharray="${o.dash}"` : ''} ${o.shadow ? 'filter="url(#sh)"' : ''} ${o.opacity ? `opacity="${o.opacity}"` : ''}/>`;
}

// Box with centred title (+ optional subtitle), optional icon on the left or top.
function box(x, y, w, h, title, o = {}) {
  let s = rect(x, y, w, h, o);
  const tc = o.color || C.ink;
  const size = o.size || 15;
  if (o.icon && o.iconPos === 'left') {
    const is = o.iconSize || 22;
    s += icon(o.icon, x + 14, y + h / 2 - is / 2, is, o.iconColor || tc);
    const tx = x + 14 + is + 10;
    if (o.sub) {
      s += text(tx, y + h / 2 - 3, title, { size, weight: o.weight || 600, fill: tc });
      s += text(tx, y + h / 2 + 14, o.sub, { size: o.subSize || 12, fill: o.subColor || C.muted, lh: 15 });
    } else s += text(tx, y + h / 2, title, { size, weight: o.weight || 600, fill: tc, valign: 'middle' });
    return s;
  }
  let cy = y + h / 2;
  if (o.icon) {
    const is = o.iconSize || 24;
    const lines = String(title).split('\n').length + (o.sub ? String(o.sub).split('\n').length : 0);
    const block = is + 8 + lines * size * 1.3;
    const top = y + (h - block) / 2;
    s += icon(o.icon, x + w / 2 - is / 2, top, is, o.iconColor || tc);
    cy = top + is + 8 + size;
    s += text(x + w / 2, cy, title, { size, weight: o.weight || 600, fill: tc, anchor: 'middle' });
    if (o.sub) s += text(x + w / 2, cy + String(title).split('\n').length * size * 1.3 + 2, o.sub, { size: o.subSize || 12, fill: o.subColor || C.muted, anchor: 'middle', lh: 15 });
    return s;
  }
  if (o.sub) {
    const tl = String(title).split('\n').length, sl = String(o.sub).split('\n').length;
    const lh = size * 1.3, slh = (o.subSize || 12) * 1.3;
    const block = tl * lh + sl * slh + 2;
    const top = y + (h - block) / 2 + size * 0.95;
    s += text(x + w / 2, top, title, { size, weight: o.weight || 600, fill: tc, anchor: 'middle', lh });
    s += text(x + w / 2, top + (tl - 1) * lh + slh + 3, o.sub, { size: o.subSize || 12, fill: o.subColor || C.muted, anchor: 'middle', lh: slh });
  } else {
    s += text(x + w / 2, cy, title, { size, weight: o.weight || 600, fill: tc, anchor: 'middle', valign: 'middle' });
  }
  return s;
}

// Vertical cylinder (database / cache).
function cyl(x, y, w, h, title, o = {}) {
  const ry = o.ry || 12, fill = o.fill || C.lightBlue, st = o.stroke || C.lightBlueStroke, sw = o.sw || 1.8;
  let s = `<path d="M${x},${y + ry} L${x},${y + h - ry} A${w / 2},${ry} 0 0 0 ${x + w},${y + h - ry} L${x + w},${y + ry}" fill="${fill}" stroke="${st}" stroke-width="${sw}"/>`;
  s += `<ellipse cx="${x + w / 2}" cy="${y + ry}" rx="${w / 2}" ry="${ry}" fill="${o.top || fill}" stroke="${st}" stroke-width="${sw}"/>`;
  s += box(x, y + ry * 1.4, w, h - ry * 1.6, title, { ...o, fill: 'none', stroke: 'none' });
  return s;
}

// Horizontal cylinder (stream / pipeline).
function hcyl(x, y, w, h, title, o = {}) {
  const rx = o.rx || 14, fill = o.fill || C.lightBlue, st = o.stroke || C.lightBlueStroke, sw = o.sw || 1.8;
  let s = `<path d="M${x + rx},${y} L${x + w - rx},${y} A${rx},${h / 2} 0 0 1 ${x + w - rx},${y + h} L${x + rx},${y + h} A${rx},${h / 2} 0 0 1 ${x + rx},${y}" fill="${fill}" stroke="${st}" stroke-width="${sw}"/>`;
  s += `<ellipse cx="${x + rx}" cy="${y + h / 2}" rx="${rx}" ry="${h / 2}" fill="${o.top || fill}" stroke="${st}" stroke-width="${sw}"/>`;
  s += box(x + rx, y, w - rx, h, title, { ...o, fill: 'none', stroke: 'none' });
  return s;
}

// Stack of 3 offset boxes (like "AWS ELB" / "Micro service" in the reference).
function stack(x, y, w, h, title, o = {}) {
  const d = o.offset || 8;
  let s = '';
  s += rect(x + 2 * d, y - 2 * d, w, h, { fill: o.back || '#EEF2F6', stroke: o.stroke || C.lightBlueStroke, sw: 1.2, r: o.r ?? 3 });
  s += rect(x + d, y - d, w, h, { fill: o.back || '#EEF2F6', stroke: o.stroke || C.lightBlueStroke, sw: 1.2, r: o.r ?? 3 });
  s += box(x, y, w, h, title, { r: 3, ...o });
  return s;
}

function badge(x, y, n, o = {}) {
  const r = o.r || 15;
  return `<circle cx="${x}" cy="${y}" r="${r}" fill="${o.fill || C.coral}" stroke="${o.stroke || C.coralStroke}" stroke-width="1.8"/>` +
    text(x, y, String(n), { size: o.size || 15, weight: 700, fill: o.color || '#5B1A18', anchor: 'middle', valign: 'middle' });
}

function arrowHead(x, y, ang, color, size = 10) {
  const a1 = ang + Math.PI - 0.42, a2 = ang + Math.PI + 0.42;
  return `<polygon points="${x},${y} ${x + size * Math.cos(a1)},${y + size * Math.sin(a1)} ${x + size * Math.cos(a2)},${y + size * Math.sin(a2)}" fill="${color}"/>`;
}

// Polyline with rounded corners and optional arrow heads at either end.
function line(pts, o = {}) {
  const color = o.color || C.ink, w = o.width || 2, r = o.radius ?? 10, hs = o.head || 10;
  const p = pts.map((q) => [...q]);
  const ang = (a, b) => Math.atan2(b[1] - a[1], b[0] - a[0]);
  const endA = ang(p[p.length - 2], p[p.length - 1]);
  const startA = ang(p[1], p[0]);
  // pull the ends in so the stroke doesn't poke through the arrow tip
  if (o.end) { const q = p[p.length - 1]; q[0] -= Math.cos(endA) * hs * 0.8; q[1] -= Math.sin(endA) * hs * 0.8; }
  if (o.start) { const q = p[0]; q[0] -= Math.cos(startA) * hs * 0.8; q[1] -= Math.sin(startA) * hs * 0.8; }
  let d = `M${p[0][0]},${p[0][1]}`;
  for (let i = 1; i < p.length - 1; i++) {
    const [ax, ay] = p[i - 1], [bx, by] = p[i], [cx, cy] = p[i + 1];
    const l1 = Math.hypot(bx - ax, by - ay), l2 = Math.hypot(cx - bx, cy - by);
    const rr = Math.min(r, l1 / 2, l2 / 2);
    const x1 = bx - ((bx - ax) / l1) * rr, y1 = by - ((by - ay) / l1) * rr;
    const x2 = bx + ((cx - bx) / l2) * rr, y2 = by + ((cy - by) / l2) * rr;
    d += ` L${x1},${y1} Q${bx},${by} ${x2},${y2}`;
  }
  d += ` L${p[p.length - 1][0]},${p[p.length - 1][1]}`;
  let s = `<path d="${d}" fill="none" stroke="${color}" stroke-width="${w}" ${o.dash ? `stroke-dasharray="${o.dash}"` : ''} stroke-linecap="round" stroke-linejoin="round"/>`;
  if (o.end) s += arrowHead(pts[pts.length - 1][0], pts[pts.length - 1][1], endA, color, hs);
  if (o.start) s += arrowHead(pts[0][0], pts[0][1], startA, color, hs);
  return s;
}

// Pill whose width is fixed by the browser after fonts load (see AUTOSIZE_JS).
// align: 'start' (x is left edge) or 'middle' (x is centre).
function pill(x, y, label, o = {}) {
  const h = o.h || 26, size = o.size || 13;
  return `<g class="autopill" data-x="${x}" data-align="${o.align || 'start'}" data-pad="${o.pad || 12}" data-icon="${o.icon ? 1 : 0}">` +
    `<rect x="${x}" y="${y}" width="10" height="${h}" rx="${o.r ?? h / 2}" fill="${o.fill || C.soft}" stroke="${o.stroke || 'none'}" stroke-width="${o.sw || 1.2}"/>` +
    (o.icon ? icon(o.icon, x, y + h / 2 - (size + 2) / 2, size + 2, o.color || C.ink) : '') +
    `<text x="${x}" y="${y + h / 2 + size * 0.36}" font-size="${size}" font-weight="${o.weight || 500}" fill="${o.color || C.ink}">${esc(label)}</text></g>`;
}

// Row of pills laid out left-to-right by the browser, wrapping at maxW.
function pillRow(x, y, items, o = {}) {
  return `<g class="pillrow" data-x="${x}" data-y="${y}" data-maxw="${o.maxW || 800}" data-gap="${o.gap || 8}" data-lgap="${o.lgap || 8}">` +
    items.map((it) => pill(0, 0, typeof it === 'string' ? it : it.label, { ...o, ...(typeof it === 'string' ? {} : it) })).join('') + '</g>';
}

const AUTOSIZE_JS = `
for (const g of document.querySelectorAll('.autopill')) {
  const t = g.querySelector('text'), r = g.querySelector('rect'), ic = g.querySelector('svg');
  const pad = +g.dataset.pad, tw = t.getComputedTextLength();
  const iw = ic ? (+ic.getAttribute('width') + 6) : 0;
  const w = tw + iw + pad * 2;
  let x = +g.dataset.x; if (g.dataset.align === 'middle') x -= w / 2;
  r.setAttribute('x', x); r.setAttribute('width', w);
  if (ic) ic.setAttribute('x', x + pad);
  t.setAttribute('x', x + pad + iw);
  g.dataset.w = w;
}
for (const row of document.querySelectorAll('.pillrow')) {
  const x0 = +row.dataset.x, y0 = +row.dataset.y, maxw = +row.dataset.maxw, gap = +row.dataset.gap, lgap = +row.dataset.lgap;
  let cx = 0, cy = 0;
  for (const g of row.querySelectorAll('.autopill')) {
    const w = +g.dataset.w, h = +g.querySelector('rect').getAttribute('height');
    if (cx > 0 && cx + w > maxw) { cx = 0; cy += h + lgap; }
    g.setAttribute('transform', 'translate(' + (x0 + cx) + ',' + (y0 + cy) + ')');
    cx += w + gap;
  }
}
for (const e of document.querySelectorAll('.autoell')) {
  const t = e.querySelector('text'); const el = e.querySelector('ellipse'); const el2 = e.querySelectorAll('ellipse')[1];
  const tw = t.getBBox().width; const rx = Math.max(+e.dataset.minrx, tw / 2 + +e.dataset.pad);
  el.setAttribute('rx', rx); if (el2) el2.setAttribute('rx', rx - 5);
  if (e.dataset.ul) {
    const b = t.getBBox(), ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    const y = b.y + b.height - 1.5;
    ln.setAttribute('x1', b.x); ln.setAttribute('x2', b.x + b.width); ln.setAttribute('y1', y); ln.setAttribute('y2', y);
    ln.setAttribute('stroke', t.getAttribute('fill')); ln.setAttribute('stroke-width', '1.4');
    if (e.dataset.ul === 'dash') ln.setAttribute('stroke-dasharray', '4 3');
    e.appendChild(ln);
  }
}
`;

const DEFS = `<defs>
<filter id="sh" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#0F2A44" flood-opacity="0.12"/></filter>
<filter id="shs" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="1" stdDeviation="1.5" flood-color="#0F2A44" flood-opacity="0.15"/></filter>
<pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M24 0 L0 0 0 24" fill="none" stroke="#E2E8F0" stroke-width="0.6"/></pattern>
</defs>`;

function svgDoc(w, h, body, bg = C.white) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" font-family="Inter, sans-serif">${DEFS}<rect width="${w}" height="${h}" fill="${bg}"/>${body}</svg>`;
}

let _browser = null;
async function render(name, w, h, body, o = {}) {
  let pw;
  try { pw = require('playwright'); } catch { pw = require('/opt/node22/lib/node_modules/playwright'); }
  const { chromium } = pw;
  if (!_browser) _browser = await chromium.launch();
  const page = await _browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: o.scale || 2.5 });
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;padding:0}svg{display:block}text{font-kerning:normal}</style></head><body>${svgDoc(w, h, body, o.bg)}<script>document.fonts.ready.then(()=>{${AUTOSIZE_JS};document.body.dataset.done=1})</script></body></html>`;
  fs.writeFileSync(path.join(__dirname, '.last.html'), html);
  await page.setContent(html);
  await page.waitForSelector('body[data-done="1"]');
  fs.mkdirSync(OUT_DIR, { recursive: true });
  await page.screenshot({ path: path.join(OUT_DIR, name + '.png'), clip: { x: 0, y: 0, width: w, height: h } });
  await page.close();
  console.log('rendered', name);
}
async function done() { if (_browser) await _browser.close(); }

module.exports = { C, esc, icon, text, rect, box, cyl, hcyl, stack, badge, line, arrowHead, pill, pillRow, render, done };
