// Database diagrams: two Chen-notation ER diagrams (in the style of the
// reference hospital ERD) and a physical table map.
const L = require('./lib');
const { C, text, rect, icon, line, esc } = L;

const K = {
  ent: '#2F86B0', entStroke: '#1F6E8F',
  attr: '#15B39B', attrStroke: '#0E9682',
  rel: '#5E6E8C', relStroke: '#46546E',
  weak: '#E6EDB7', weakStroke: '#A3B04F',
  multi: '#FFD0D8', multiStroke: '#E07A8E',
  isa: '#FBE7E3', isaStroke: '#D98F80',
  wire: '#1F2937',
};

// ---------------------------------------------------------------- Chen builder
function chen(spec) {
  const E = spec.entities, R = spec.rels;
  let under = '', over = '', marks = '';
  const center = (id) => (E[id] ? E[id] : R[id]);

  // attribute lines + ellipses
  for (const a of spec.attrs) {
    const e = E[a.of];
    under += `<line x1="${e.x}" y1="${e.y}" x2="${a.x}" y2="${a.y}" stroke="${K.wire}" stroke-width="1.3"/>`;
    const multi = a.t === 'multi';
    const fill = multi ? K.multi : K.attr, st = multi ? K.multiStroke : K.attrStroke, tc = multi ? '#5B1F2B' : '#fff';
    over += `<g class="autoell" data-minrx="${a.minrx || 44}" data-pad="${a.pad || 15}" data-ul="${a.t === 'key' ? 'solid' : a.t === 'partial' ? 'dash' : ''}">` +
      `<ellipse cx="${a.x}" cy="${a.y}" rx="50" ry="19" fill="${fill}" stroke="${st}" stroke-width="1.6"/>` +
      (multi ? `<ellipse cx="${a.x}" cy="${a.y}" rx="45" ry="14" fill="none" stroke="${st}" stroke-width="1.3"/>` : '') +
      `<text x="${a.x}" y="${a.y + 4.6}" font-size="13" font-weight="600" fill="${tc}" text-anchor="middle">${esc(a.label)}</text></g>`;
  }

  // relationship links (entity side -> diamond), with cardinality marker at the entity
  for (const l of spec.links) {
    const e = E[l.e], r = R[l.r];
    const off = l.off || 0;
    let sx, sy, dir;
    if (l.side === 'right') { sx = e.x + e.w / 2; sy = e.y + off; dir = [1, 0]; }
    if (l.side === 'left') { sx = e.x - e.w / 2; sy = e.y + off; dir = [-1, 0]; }
    if (l.side === 'top') { sx = e.x + off; sy = e.y - e.h / 2; dir = [0, -1]; }
    if (l.side === 'bottom') { sx = e.x + off; sy = e.y + e.h / 2; dir = [0, 1]; }
    const pts = [[sx, sy], ...(l.via || [])];
    const prev = pts[pts.length - 1];
    const rw = r.w || 118, rh = r.h || 60;
    let end;
    if (Math.abs(prev[1] - r.y) < 0.5) end = [prev[0] < r.x ? r.x - rw / 2 : r.x + rw / 2, r.y];
    else end = [r.x, prev[1] < r.y ? r.y - rh / 2 : r.y + rh / 2];
    pts.push(end);
    under += line(pts, { color: K.wire, width: 1.6, radius: 0 });
    marks += marker(sx, sy, dir, l.card);
  }

  // ISA
  if (spec.isa) {
    const s = spec.isa, p = E[s.parent];
    under += `<line x1="${p.x}" y1="${p.y + p.h / 2}" x2="${s.x}" y2="${s.y - 22}" stroke="${K.wire}" stroke-width="1.6"/>`;
    for (const c of s.children) {
      const ce = E[c];
      under += line([[s.x, s.y + 20], [s.x, s.y + 34], [ce.x, s.y + 34], [ce.x, ce.y - ce.h / 2]], { color: K.wire, width: 1.6, radius: 0 });
    }
    over += `<polygon points="${s.x},${s.y - 24} ${s.x + 30},${s.y + 20} ${s.x - 30},${s.y + 20}" fill="${K.isa}" stroke="${K.isaStroke}" stroke-width="1.6"/>`;
    over += text(s.x, s.y + 13, 'ISA', { size: 11.5, weight: 700, fill: '#9A4B3F', anchor: 'middle' });
    if (s.note) over += text(s.x + 40, s.y + 5, s.note, { size: 11.5, fill: C.muted, style: 'italic' });
  }

  // diamonds
  for (const id in R) {
    const r = R[id], w = r.w || 118, h = r.h || 60;
    over += `<polygon points="${r.x},${r.y - h / 2} ${r.x + w / 2},${r.y} ${r.x},${r.y + h / 2} ${r.x - w / 2},${r.y}" fill="${K.rel}" stroke="${K.relStroke}" stroke-width="1.6"/>`;
    if (r.ident) over += `<polygon points="${r.x},${r.y - h / 2 + 7} ${r.x + w / 2 - 12},${r.y} ${r.x},${r.y + h / 2 - 7} ${r.x - w / 2 + 12},${r.y}" fill="none" stroke="#C7D0E0" stroke-width="1.3"/>`;
    over += text(r.x, r.y + 4.5, r.label, { size: 13, weight: 700, fill: '#fff', anchor: 'middle' });
  }
  // entities
  for (const id in E) {
    const e = E[id];
    const x = e.x - e.w / 2, y = e.y - e.h / 2;
    if (e.weak) {
      over += `<rect x="${x}" y="${y}" width="${e.w}" height="${e.h}" fill="${K.weak}" stroke="${K.weakStroke}" stroke-width="1.8"/>`;
      over += `<rect x="${x + 5}" y="${y + 5}" width="${e.w - 10}" height="${e.h - 10}" fill="none" stroke="${K.weakStroke}" stroke-width="1.3"/>`;
      over += text(e.x, e.y + 5, e.label, { size: 14.5, weight: 700, fill: '#3F4A12', anchor: 'middle' });
    } else {
      over += `<rect x="${x}" y="${y}" width="${e.w}" height="${e.h}" fill="${K.ent}" stroke="${K.entStroke}" stroke-width="1.6" filter="url(#shs)"/>`;
      over += text(e.x, e.y + 5, e.label, { size: 14.5, weight: 700, fill: '#fff', anchor: 'middle' });
    }
  }
  return under + over + marks;
}

// Crow's-foot marker at (x,y) on the entity border, `d` points away from it.
function marker(x, y, d, type) {
  const [dx, dy] = d, px = -dy, py = dx;
  const P = (t, s = 0) => [x + dx * t + px * s, y + dy * t + py * s];
  const seg = (a, b) => `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="${K.wire}" stroke-width="1.6"/>`;
  const bar = (t) => seg(P(t, -7), P(t, 7));
  const circ = (t) => { const c = P(t); return `<circle cx="${c[0]}" cy="${c[1]}" r="5" fill="#fff" stroke="${K.wire}" stroke-width="1.6"/>`; };
  const crow = () => seg(P(13), P(0, -8)) + seg(P(13), P(0, 8)) + seg(P(13), P(0));
  if (type === 'one') return bar(9) + bar(15);
  if (type === 'zero_one') return bar(9) + circ(20);
  if (type === 'one_many') return crow() + bar(18);
  if (type === 'zero_many') return crow() + circ(22);
  return '';
}

function legend(x, y) {
  let s = rect(x, y, 372, 176, { fill: '#fff', stroke: C.line, r: 10 });
  s += text(x + 14, y + 22, 'HOW TO READ THIS', { size: 11, weight: 700, fill: C.muted, ls: 1 });
  const row = (i, j) => [x + 16 + j * 160, y + 44 + i * 30];
  let [a, b] = row(0, 0);
  s += `<rect x="${a}" y="${b - 10}" width="40" height="20" fill="${K.ent}"/>` + text(a + 50, b + 4, 'Entity (table)', { size: 11.5 });
  [a, b] = row(0, 1);
  s += `<rect x="${a}" y="${b - 10}" width="40" height="20" fill="${K.weak}" stroke="${K.weakStroke}" stroke-width="1.5"/><rect x="${a + 3}" y="${b - 7}" width="34" height="14" fill="none" stroke="${K.weakStroke}"/>` + text(a + 50, b + 4, 'Weak entity', { size: 11.5 });
  [a, b] = row(1, 0);
  s += `<polygon points="${a + 20},${b - 11} ${a + 40},${b} ${a + 20},${b + 11} ${a},${b}" fill="${K.rel}"/>` + text(a + 50, b + 4, 'Relationship', { size: 11.5 });
  [a, b] = row(1, 1);
  s += `<ellipse cx="${a + 20}" cy="${b}" rx="20" ry="10" fill="${K.attr}"/>` + text(a + 50, b + 4, 'Attribute (key underlined)', { size: 11.5 });
  [a, b] = row(2, 0);
  s += `<ellipse cx="${a + 20}" cy="${b}" rx="20" ry="10" fill="${K.multi}" stroke="${K.multiStroke}"/><ellipse cx="${a + 20}" cy="${b}" rx="15" ry="6" fill="none" stroke="${K.multiStroke}"/>` + text(a + 50, b + 4, 'Multi-valued', { size: 11.5 });
  [a, b] = row(2, 1);
  s += `<polygon points="${a + 20},${b - 11} ${a + 36},${b + 10} ${a + 4},${b + 10}" fill="${K.isa}" stroke="${K.isaStroke}"/>` + text(a + 50, b + 4, 'ISA (subtype)', { size: 11.5 });
  // cardinality
  const cy = y + 140;
  const cards = [['one', 'one'], ['zero_one', '0 or 1'], ['one_many', '1 or more'], ['zero_many', '0 or more']];
  cards.forEach(([t, l], i) => {
    const cx = x + 16 + i * 80;
    s += `<line x1="${cx}" y1="${cy}" x2="${cx + 34}" y2="${cy}" stroke="${K.wire}" stroke-width="1.6"/><line x1="${cx}" y1="${cy - 10}" x2="${cx}" y2="${cy + 10}" stroke="${K.wire}" stroke-width="2"/>`;
    s += marker(cx, cy, [1, 0], t);
    s += text(cx, cy + 26, l, { size: 11, fill: C.muted });
  });
  return s;
}

const D = {};

// ------------------------------------------------ ER 1: search results model
D.er_search = async () => {
  const W = 1500, H = 960;
  const spec = {
    entities: {
      SR: { x: 250, y: 390, w: 196, h: 50, label: 'Search Request' },
      PR: { x: 650, y: 390, w: 176, h: 52, label: 'Page Result', weak: true },
      AO: { x: 1060, y: 390, w: 170, h: 50, label: 'AI Overview' },
      AS: { x: 1380, y: 390, w: 170, h: 52, label: 'AIO Source', weak: true },
      KP: { x: 1060, y: 720, w: 190, h: 50, label: 'Knowledge Panel' },
      RI: { x: 560, y: 730, w: 170, h: 50, label: 'Result Item' },
      OR: { x: 400, y: 905, w: 150, h: 46, label: 'Organic' },
      PA: { x: 720, y: 905, w: 150, h: 46, label: 'Paid Ad' },
    },
    rels: {
      RET: { x: 450, y: 390, label: 'Returns', ident: true },
      HAS: { x: 855, y: 390, label: 'Has' },
      CIT: { x: 1222, y: 390, w: 104, label: 'Cites', ident: true },
      SHW: { x: 855, y: 720, label: 'Shows' },
      LST: { x: 560, y: 585, label: 'Lists' },
    },
    attrs: [
      { of: 'SR', x: 95, y: 250, label: 'request_id', t: 'key' },
      { of: 'SR', x: 220, y: 228, label: 'url' },
      { of: 'SR', x: 350, y: 252, label: 'results' },
      { of: 'SR', x: 70, y: 390, label: 'country' },
      { of: 'SR', x: 85, y: 520, label: 'status_code' },
      { of: 'SR', x: 215, y: 555, label: 'error_code' },
      { of: 'SR', x: 360, y: 520, label: 'requests_used' },
      { of: 'SR', x: 250, y: 640, label: 'elapsed_ms' },
      { of: 'PR', x: 575, y: 240, label: 'page_no', t: 'partial' },
      { of: 'PR', x: 740, y: 240, label: 'number_of_results' },
      { of: 'PR', x: 815, y: 490, label: 'suggestions', t: 'multi' },
      { of: 'PR', x: 790, y: 590, label: 'corrections', t: 'multi' },
      { of: 'AO', x: 960, y: 250, label: 'aio_id', t: 'key' },
      { of: 'AO', x: 1110, y: 235, label: 'state' },
      { of: 'AO', x: 980, y: 530, label: 'intro', t: 'multi' },
      { of: 'AO', x: 1140, y: 545, label: 'sections', t: 'multi' },
      { of: 'AS', x: 1300, y: 240, label: 'position', t: 'partial' },
      { of: 'AS', x: 1440, y: 265, label: 'url' },
      { of: 'AS', x: 1300, y: 540, label: 'title' },
      { of: 'AS', x: 1440, y: 515, label: 'snippet' },
      { of: 'KP', x: 1000, y: 830, label: 'panel_id', t: 'key' },
      { of: 'KP', x: 1150, y: 850, label: 'title' },
      { of: 'KP', x: 1280, y: 790, label: 'subtitle' },
      { of: 'KP', x: 1300, y: 655, label: 'description' },
      { of: 'KP', x: 1400, y: 720, label: 'source_url' },
      { of: 'KP', x: 1335, y: 880, label: 'facts', t: 'multi' },
      { of: 'RI', x: 385, y: 660, label: 'item_id', t: 'key' },
      { of: 'RI', x: 365, y: 760, label: 'position' },
      { of: 'RI', x: 740, y: 640, label: 'title' },
      { of: 'RI', x: 755, y: 790, label: 'url' },
      { of: 'RI', x: 650, y: 820, label: 'content' },
      { of: 'OR', x: 225, y: 905, label: 'sub_links', t: 'multi' },
      { of: 'PA', x: 900, y: 905, label: 'ad_block' },
    ],
    links: [
      { e: 'SR', side: 'right', r: 'RET', card: 'one' },
      { e: 'PR', side: 'left', r: 'RET', card: 'one_many' },
      { e: 'PR', side: 'right', r: 'HAS', card: 'one' },
      { e: 'AO', side: 'left', r: 'HAS', card: 'zero_one' },
      { e: 'AO', side: 'right', r: 'CIT', card: 'one' },
      { e: 'AS', side: 'left', r: 'CIT', card: 'one_many' },
      { e: 'PR', side: 'bottom', off: 10, r: 'SHW', via: [[660, 720]], card: 'one' },
      { e: 'KP', side: 'left', r: 'SHW', card: 'zero_one' },
      { e: 'PR', side: 'bottom', off: -90, r: 'LST', via: [[560, 470]], card: 'one' },
      { e: 'RI', side: 'top', r: 'LST', card: 'one_many' },
    ],
    isa: { x: 560, y: 820, parent: 'RI', children: ['OR', 'PA'] },
  };
  let s = chen(spec);
  s += legend(20, 20);
  // notes that carry business rules
  s += rect(1170, 20, 310, 150, { fill: '#F8FAFC', stroke: C.line, r: 10 });
  s += text(1186, 44, 'RULES THE MODEL ENFORCES', { size: 11, weight: 700, fill: C.muted, ls: 1 });
  const rules = ['A valid page has 1+ organic result.', 'A present AI Overview has 1+ source,', 'each with a real URL.', 'Rows are written only for status 200;', 'failures keep the request row only.'];
  rules.forEach((r, i) => { s += text(1186, 68 + i * 19, r, { size: 12, fill: C.ink }); });
  await L.render('09_er_search_data', W, H, s);
};

// ------------------------------------------ ER 2: accounts, proxies, operations
D.er_ops = async () => {
  const W = 1500, H = 930;
  const spec = {
    entities: {
      CL: { x: 200, y: 170, w: 150, h: 50, label: 'Client' },
      AK: { x: 200, y: 500, w: 150, h: 50, label: 'API Key' },
      DU: { x: 200, y: 830, w: 176, h: 52, label: 'Daily Usage', weak: true },
      SR: { x: 700, y: 500, w: 196, h: 50, label: 'Search Request' },
      BR: { x: 700, y: 170, w: 190, h: 50, label: 'Benchmark Run' },
      AR: { x: 660, y: 830, w: 160, h: 52, label: 'Artifact', weak: true },
      PS: { x: 1180, y: 500, w: 180, h: 50, label: 'Proxy Session' },
      PP: { x: 1180, y: 170, w: 180, h: 50, label: 'Proxy Provider' },
      WK: { x: 1190, y: 820, w: 150, h: 50, label: 'Worker' },
    },
    rels: {
      OWN: { x: 200, y: 335, label: 'Owns' },
      SND: { x: 440, y: 500, label: 'Sends' },
      TRK: { x: 200, y: 670, label: 'Tracks', ident: true },
      INC: { x: 700, y: 335, label: 'Includes' },
      SAV: { x: 660, y: 680, label: 'Saves', ident: true },
      USE: { x: 945, y: 500, label: 'Uses' },
      OPN: { x: 1180, y: 335, label: 'Opens' },
      RUN: { x: 960, y: 820, label: 'Runs' },
    },
    attrs: [
      { of: 'CL', x: 70, y: 80, label: 'client_id', t: 'key' },
      { of: 'CL', x: 200, y: 55, label: 'name' },
      { of: 'CL', x: 335, y: 80, label: 'plan' },
      { of: 'CL', x: 360, y: 190, label: 'status' },
      { of: 'AK', x: 60, y: 420, label: 'key_id', t: 'key' },
      { of: 'AK', x: 55, y: 500, label: 'key_prefix' },
      { of: 'AK', x: 65, y: 585, label: 'key_hash' },
      { of: 'AK', x: 345, y: 420, label: 'rate_limit' },
      { of: 'AK', x: 345, y: 590, label: 'monthly_quota' },
      { of: 'DU', x: 55, y: 760, label: 'day', t: 'partial' },
      { of: 'DU', x: 60, y: 880, label: 'requests' },
      { of: 'DU', x: 170, y: 910, label: 'valid' },
      { of: 'DU', x: 320, y: 905, label: 'google_requests' },
      { of: 'DU', x: 365, y: 770, label: 'bytes_in' },
      { of: 'SR', x: 565, y: 415, label: 'request_id', t: 'key' },
      { of: 'SR', x: 810, y: 400, label: 'status_code' },
      { of: 'SR', x: 925, y: 425, label: 'created_at' },
      { of: 'SR', x: 500, y: 592, label: 'requests_used' },
      { of: 'BR', x: 520, y: 80, label: 'run_id', t: 'key' },
      { of: 'BR', x: 650, y: 55, label: 'corpus' },
      { of: 'BR', x: 790, y: 55, label: 'valid_rate' },
      { of: 'BR', x: 910, y: 110, label: 'p95_ms' },
      { of: 'BR', x: 900, y: 235, label: 'stopped_reason' },
      { of: 'AR', x: 505, y: 765, label: 'page_no', t: 'partial' },
      { of: 'AR', x: 480, y: 875, label: 'html_key' },
      { of: 'AR', x: 640, y: 910, label: 'screenshot_key' },
      { of: 'AR', x: 815, y: 890, label: 'expires_at' },
      { of: 'PS', x: 1050, y: 420, label: 'session_id', t: 'key' },
      { of: 'PS', x: 1330, y: 410, label: 'exit_ip' },
      { of: 'PS', x: 1400, y: 500, label: 'exit_ip_after' },
      { of: 'PS', x: 1340, y: 590, label: 'ip_changed' },
      { of: 'PS', x: 1195, y: 620, label: 'end_reason' },
      { of: 'PP', x: 1050, y: 75, label: 'provider_id', t: 'key' },
      { of: 'PP', x: 1190, y: 55, label: 'name' },
      { of: 'PP', x: 1330, y: 80, label: 'mode' },
      { of: 'PP', x: 1390, y: 180, label: 'country' },
      { of: 'PP', x: 1370, y: 265, label: 'url_template' },
      { of: 'WK', x: 1100, y: 715, label: 'worker_id', t: 'key' },
      { of: 'WK', x: 1300, y: 725, label: 'host' },
      { of: 'WK', x: 1360, y: 830, label: 'slots' },
      { of: 'WK', x: 1290, y: 905, label: 'version' },
      { of: 'WK', x: 1120, y: 905, label: 'status' },
    ],
    links: [
      { e: 'CL', side: 'bottom', r: 'OWN', card: 'one' },
      { e: 'AK', side: 'top', r: 'OWN', card: 'one_many' },
      { e: 'AK', side: 'right', r: 'SND', card: 'one' },
      { e: 'SR', side: 'left', r: 'SND', card: 'zero_many' },
      { e: 'AK', side: 'bottom', r: 'TRK', card: 'one' },
      { e: 'DU', side: 'top', r: 'TRK', card: 'zero_many' },
      { e: 'BR', side: 'bottom', r: 'INC', card: 'zero_one' },
      { e: 'SR', side: 'top', r: 'INC', card: 'zero_many' },
      { e: 'SR', side: 'bottom', off: -40, r: 'SAV', card: 'one' },
      { e: 'AR', side: 'top', r: 'SAV', card: 'zero_many' },
      { e: 'SR', side: 'right', r: 'USE', card: 'zero_many' },
      { e: 'PS', side: 'left', r: 'USE', card: 'zero_one' },
      { e: 'PP', side: 'bottom', r: 'OPN', card: 'one' },
      { e: 'PS', side: 'top', r: 'OPN', card: 'zero_many' },
      { e: 'SR', side: 'bottom', off: 70, r: 'RUN', via: [[770, 820]], card: 'zero_many' },
      { e: 'WK', side: 'left', r: 'RUN', card: 'one' },
    ],
  };
  let s = chen(spec);
  await L.render('10_er_operations', W, H, s);
};

// ------------------------------------------------------------ physical tables
const TABLES = {
  clients: ['acc', [['id', 'uuid', 'PK'], ['name', 'text'], ['plan', 'text'], ['status', 'text'], ['created_at', 'timestamptz']]],
  api_keys: ['acc', [['id', 'uuid', 'PK'], ['client_id', 'uuid', 'FK'], ['key_prefix', 'char(8)'], ['key_hash', 'bytea'], ['label', 'text'], ['rate_limit_rpm', 'int'], ['monthly_quota', 'int'], ['status', 'text'], ['revoked_at', 'timestamptz']]],
  usage_daily: ['acc', [['api_key_id', 'uuid', 'PK FK'], ['day', 'date', 'PK'], ['requests', 'int'], ['valid', 'int'], ['google_requests', 'int'], ['bytes_in', 'bigint']]],
  benchmark_runs: ['ops', [['id', 'uuid', 'PK'], ['corpus', 'text'], ['started_at', 'timestamptz'], ['finished_at', 'timestamptz'], ['valid_rate', 'numeric(5,2)'], ['p50_ms', 'int'], ['p95_ms', 'int'], ['stopped_reason', 'text'], ['report_key', 'text']]],
  search_requests: ['req', [['id', 'uuid', 'PK'], ['api_key_id', 'uuid', 'FK'], ['benchmark_run_id', 'uuid', 'FK'], ['proxy_session_id', 'uuid', 'FK'], ['worker_id', 'text', 'FK'], ['url', 'text'], ['results', 'smallint'], ['country', 'char(2)'], ['language', 'varchar(8)'], ['status_code', 'smallint'], ['error_code', 'text'], ['error_message', 'text'], ['aio_state', 'text'], ['requests_used', 'int'], ['google_requests', 'jsonb'], ['elapsed_ms', 'int'], ['bytes_in', 'bigint'], ['bytes_in_partial', 'bool'], ['parser_version', 'text'], ['created_at', 'timestamptz']], 'partitioned by month'],
  artifacts: ['req', [['search_request_id', 'uuid', 'PK FK'], ['page_no', 'smallint', 'PK'], ['html_key', 'text'], ['screenshot_key', 'text'], ['expires_at', 'timestamptz']]],
  page_results: ['res', [['search_request_id', 'uuid', 'PK FK'], ['page_no', 'smallint', 'PK'], ['number_of_results', 'bigint'], ['suggestions', 'text[]'], ['corrections', 'text[]'], ['timings', 'jsonb']]],
  proxy_sessions: ['ops', [['id', 'uuid', 'PK'], ['provider_id', 'uuid', 'FK'], ['exit_ip', 'inet'], ['exit_ip_after', 'inet'], ['ip_changed', 'bool'], ['started_at', 'timestamptz'], ['ended_at', 'timestamptz'], ['end_reason', 'text'], ['requests_served', 'int'], ['captcha_count', 'int']]],
  proxy_providers: ['ops', [['id', 'uuid', 'PK'], ['name', 'text'], ['mode', 'static | list'], ['country', 'char(2)'], ['url_template', 'text (masked)'], ['secret_arn', 'text']]],
  workers: ['ops', [['id', 'text', 'PK'], ['host', 'text'], ['slots', 'smallint'], ['version', 'text'], ['status', 'text'], ['last_seen_at', 'timestamptz']]],
  result_items: ['res', [['id', 'bigint', 'PK'], ['search_request_id', 'uuid', 'FK'], ['page_no', 'smallint', 'FK'], ['kind', 'organic | paid'], ['ad_block', 'top | bottom'], ['position', 'smallint'], ['title', 'text'], ['url', 'text'], ['content', 'text'], ['sub_links', 'jsonb']]],
  ai_overviews: ['res', [['id', 'bigint', 'PK'], ['search_request_id', 'uuid', 'FK'], ['page_no', 'smallint', 'FK'], ['intro', 'text[]'], ['sections', 'jsonb']]],
  aio_sources: ['res', [['ai_overview_id', 'bigint', 'PK FK'], ['position', 'smallint', 'PK'], ['title', 'text'], ['url', 'text not null'], ['snippet', 'text']]],
  knowledge_panels: ['res', [['id', 'bigint', 'PK'], ['search_request_id', 'uuid', 'FK'], ['page_no', 'smallint', 'FK'], ['title', 'text'], ['subtitle', 'text'], ['description', 'text'], ['source_url', 'text'], ['facts', 'jsonb']]],
};
const GROUP = { acc: ['#0E9682', 'Accounts & usage'], req: [C.blue, 'Requests'], res: ['#6D28D9', 'Parsed results'], ops: ['#B45309', 'Proxies & operations'] };

D.tables = async () => {
  const W = 1480, TW = 300, RH = 20, HH = 30, GAP = 22;
  const cols = [
    [30, ['clients', 'api_keys', 'usage_daily', 'benchmark_runs']],
    [400, ['search_requests', 'artifacts']],
    [770, ['page_results', 'proxy_sessions', 'proxy_providers', 'workers']],
    [1140, ['result_items', 'ai_overviews', 'aio_sources', 'knowledge_panels']],
  ];
  const pos = {};
  let s = '', maxY = 0;
  for (const [x, names] of cols) {
    let y = 20;
    for (const n of names) {
      const [g, colsDef, tag] = TABLES[n];
      const h = HH + colsDef.length * RH;
      pos[n] = { x, y, h, rows: colsDef.map((c) => c[0]) };
      s += rect(x, y, TW, h, { fill: '#fff', stroke: '#CBD5E1', r: 8, shadow: true });
      s += `<path d="M${x},${y + 8} Q${x},${y} ${x + 8},${y} L${x + TW - 8},${y} Q${x + TW},${y} ${x + TW},${y + 8} L${x + TW},${y + HH} L${x},${y + HH} Z" fill="${C.navy}"/>`;
      s += `<rect x="${x}" y="${y}" width="5" height="${HH}" fill="${GROUP[g][0]}"/>`;
      s += text(x + 14, y + 20, n, { size: 13.5, weight: 700, fill: '#fff', family: 'DejaVu Sans Mono, monospace' });
      if (tag) s += text(x + TW - 10, y + 20, tag, { size: 10.5, fill: '#A5C4DD', anchor: 'end', style: 'italic' });
      colsDef.forEach((c, i) => {
        const ry = y + HH + i * RH;
        if (i % 2) s += `<rect x="${x + 1}" y="${ry}" width="${TW - 2}" height="${RH}" fill="#F8FAFC"/>`;
        const k = c[2] || '';
        if (k.includes('PK')) s += `<rect x="${x + 8}" y="${ry + 4}" width="22" height="12" rx="3" fill="#FDE68A"/>` + text(x + 19, ry + 13.5, 'PK', { size: 8.5, weight: 800, fill: '#92400E', anchor: 'middle' });
        if (k.includes('FK')) { const fx = k.includes('PK') ? x + 33 : x + 8; s += `<rect x="${fx}" y="${ry + 4}" width="22" height="12" rx="3" fill="#DBEAFE"/>` + text(fx + 11, ry + 13.5, 'FK', { size: 8.5, weight: 800, fill: '#1E40AF', anchor: 'middle' }); }
        const nx = x + (k === 'PK FK' ? 62 : 38);
        s += text(nx, ry + 14.5, c[0], { size: 12, weight: k ? 700 : 500, fill: C.ink, family: 'DejaVu Sans Mono, monospace' });
        s += text(x + TW - 10, ry + 14.5, c[1], { size: 11, fill: C.muted, anchor: 'end' });
      });
      y += h + GAP;
    }
    maxY = Math.max(maxY, y);
  }
  // connectors: [fromTable, fromCol, fromSide, toTable, toCol, toSide, gutterX, card at "from" (many side), card at "to"]
  const rowY = (t, c) => pos[t].y + HH + pos[t].rows.indexOf(c) * RH + RH / 2;
  const sideX = (t, side) => (side === 'L' ? pos[t].x : pos[t].x + TW);
  const links = [
    ['api_keys', 'client_id', 'L', 'clients', 'id', 'L', 16, 'one_many', 'one'],
    ['usage_daily', 'api_key_id', 'R', 'api_keys', 'id', 'R', 342, 'zero_many', 'one'],
    ['search_requests', 'api_key_id', 'L', 'api_keys', 'id', 'R', 355, 'zero_many', 'one'],
    ['search_requests', 'benchmark_run_id', 'L', 'benchmark_runs', 'id', 'R', 368, 'zero_many', 'zero_one'],
    ['artifacts', 'search_request_id', 'L', 'search_requests', 'id', 'L', 380, 'zero_many', 'one'],
    ['page_results', 'search_request_id', 'L', 'search_requests', 'id', 'R', 725, 'one_many', 'one'],
    ['search_requests', 'proxy_session_id', 'R', 'proxy_sessions', 'id', 'L', 738, 'zero_many', 'zero_one'],
    ['search_requests', 'worker_id', 'R', 'workers', 'id', 'L', 751, 'zero_many', 'one'],
    ['proxy_sessions', 'provider_id', 'R', 'proxy_providers', 'id', 'R', 1090, 'zero_many', 'one'],
    ['result_items', 'search_request_id', 'L', 'page_results', 'search_request_id', 'R', 1103, 'one_many', 'one'],
    ['ai_overviews', 'search_request_id', 'L', 'page_results', 'search_request_id', 'R', 1116, 'zero_one', 'one'],
    ['knowledge_panels', 'search_request_id', 'L', 'page_results', 'search_request_id', 'R', 1116, 'zero_one', 'one'],
    ['aio_sources', 'ai_overview_id', 'R', 'ai_overviews', 'id', 'R', 1462, 'one_many', 'one'],
  ];
  let wires = '', marks = '';
  for (const [ft, fc, fs, tt, tc, ts, gx, cf, ctt] of links) {
    const a = [sideX(ft, fs), rowY(ft, fc)], b = [sideX(tt, ts), rowY(tt, tc)];
    wires += line([a, [gx, a[1]], [gx, b[1]], b], { color: '#475569', width: 1.5, radius: 6 });
    marks += marker(a[0], a[1], [fs === 'L' ? -1 : 1, 0], cf) + marker(b[0], b[1], [ts === 'L' ? -1 : 1, 0], ctt);
  }
  // legend
  const ly = maxY + 4;
  let lg = '';
  let lx = 30;
  for (const g of ['acc', 'req', 'res', 'ops']) {
    lg += `<rect x="${lx}" y="${ly}" width="14" height="14" rx="3" fill="${GROUP[g][0]}"/>` + text(lx + 22, ly + 12, GROUP[g][1], { size: 12.5, weight: 600 });
    lx += GROUP[g][1].length * 7.4 + 50;
  }
  lg += text(W - 30, ly + 12, 'PostgreSQL 16 · all times UTC · no search result is ever served from these tables', { size: 12, fill: C.muted, anchor: 'end' });
  const H = ly + 30;
  await L.render('10b_physical_schema', W, H, wires + s + marks + lg);
};

module.exports = D;

if (require.main === module) {
  (async () => {
    const names = process.argv.slice(2);
    for (const n of names.length ? names : Object.keys(D)) await D[n]();
    await L.done();
  })();
}
