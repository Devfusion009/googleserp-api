// Technical diagrams: system architecture, backend (reference style), request
// lifecycle, outcome tree, AWS deployment, tech stack map, roadmap.
const L = require('./lib');
const { C, text, rect, box, icon, line, badge, cyl, hcyl, stack, pill } = L;

const D = {};

function zone(x, y, w, h, title, sub, o = {}) {
  let s = rect(x, y, w, h, { fill: o.fill || C.softer, stroke: o.stroke || C.line, r: 14, dash: o.dash, sw: 1.4 });
  s += text(x + 14, y + 24, title, { size: 12, weight: 700, fill: o.color || C.muted, ls: 1.1 });
  if (sub) s += text(x + 14, y + 41, sub, { size: 11.5, fill: C.muted });
  return s;
}

// White component card: icon + title + small subtitle.
function comp(x, y, w, h, ic, title, sub, o = {}) {
  let s = rect(x, y, w, h, { fill: o.fill || C.white, stroke: o.stroke || '#D5DEE8', r: 10, shadow: o.shadow !== false });
  const ix = x + 12, is = o.iconSize || 20;
  s += `<rect x="${ix - 4}" y="${y + h / 2 - is / 2 - 4}" width="${is + 8}" height="${is + 8}" rx="7" fill="${o.iconBg || C.lightBlue}"/>`;
  s += icon(ic, ix, y + h / 2 - is / 2, is, o.iconColor || C.blueDark, 2);
  const tx = x + 12 + is + 12;
  if (sub) {
    const sl = sub.split('\n').length;
    const top = y + h / 2 - ((sl * 14.5) + 16) / 2 + 13;
    s += text(tx, top, title, { size: o.size || 13.5, weight: 700 });
    s += text(tx, top + 17, sub, { size: 11.5, fill: C.muted, lh: 14.5 });
  } else s += text(tx, y + h / 2, title, { size: o.size || 13.5, weight: 700, valign: 'middle' });
  return s;
}

const lbl = (x, y, t, o = {}) => {
  const w = o.w || t.length * 6.3 + 14;
  return rect(x - w / 2, y - 10, w, 20, { fill: o.fill || C.white, stroke: o.stroke || C.line, r: 10, sw: 1 }) +
    text(x, y + 4, t, { size: 11, weight: 600, fill: o.color || C.muted, anchor: 'middle' });
};

// ------------------------------------------------------------ system (technical)
D.system = async () => {
  const W = 1400, H = 900;
  let s = '';
  // zones
  s += zone(16, 16, 170, 560, 'CLIENTS');
  s += zone(206, 16, 150, 560, 'EDGE', 'AWS · HTTPS only');
  s += zone(376, 16, 250, 560, 'API TIER', 'ECS Fargate · 2+ tasks', { fill: '#F2F7FC', stroke: '#BBD3EA', color: C.blueDark });
  s += zone(646, 16, 446, 560, 'BROWSER WORKER FLEET', 'ECS on EC2 · scales on busy slots', { fill: '#F1FAF7', stroke: '#A7E3D3', color: C.tealDark });
  s += zone(1112, 16, 272, 300, 'OUTSIDE AWS', null, { fill: '#F7F4FE', stroke: '#D6CCFA', color: C.purple });
  s += zone(1112, 336, 272, 240, 'OBSERVABILITY', null, { fill: '#FFFBEB', stroke: '#F5DE9B', color: C.amber });
  s += zone(376, 596, 716, 288, 'DATA', null, { fill: '#F5F7FA', stroke: '#CBD5E1', color: C.slate });
  s += text(392, 877, 'No search result is ever cached or served twice', { size: 11.5, fill: C.red, weight: 600 });
  s += zone(16, 596, 340, 288, 'CONTROL & DELIVERY', null, { fill: '#F8FAFC', stroke: '#CBD5E1' });
  s += zone(1112, 596, 272, 288, 'ANALYTICS', null, { fill: '#F5F7FA', stroke: '#CBD5E1', color: C.slate });

  // clients
  const cl = [['laptop', 'Client apps', 'REST / SDK'], ['terminal', 'Scripts', 'cURL, cron'], ['gauge', 'Benchmark', 'run_bench.py'], ['layout-dashboard', 'Ops team', 'dashboards']];
  cl.forEach((c, i) => { s += comp(28, 64 + i * 120, 146, 78, c[0], c[1], c[2], { size: 13 }); });

  // edge
  s += comp(218, 80, 126, 70, 'waypoints', 'Route 53', 'DNS');
  s += comp(218, 230, 126, 70, 'shield', 'AWS WAF', 'IP & rate rules');
  s += comp(218, 380, 126, 70, 'split', 'ALB', 'TLS 1.2+');
  s += line([[281, 150], [281, 230]], { end: true, color: C.slate, width: 1.8 });
  s += line([[281, 300], [281, 380]], { end: true, color: C.slate, width: 1.8 });
  [103, 223, 343, 463].forEach((y) => { s += line([[174, y], [194, y]], { color: C.navy, width: 2 }); });
  s += line([[194, 103], [194, 463]], { color: C.navy, width: 2, radius: 0 });
  s += line([[194, 265], [218, 265]], { end: true, color: C.navy, width: 2.2 });

  // API tier
  const ax = 390, aw = 222;
  s += rect(ax, 66, aw, 348, { fill: C.white, stroke: '#9CC1E0', r: 12, shadow: true });
  s += `<rect x="${ax}" y="66" width="${aw}" height="42" rx="12" fill="${C.blue}"/><rect x="${ax}" y="90" width="${aw}" height="18" fill="${C.blue}"/>`;
  s += icon('server', ax + 12, 76, 20, '#fff') + text(ax + 40, 92, 'SERP Gateway', { size: 14.5, weight: 700, fill: '#fff' });
  s += text(ax + aw - 12, 92, 'FastAPI', { size: 11.5, fill: '#D6E8F5', anchor: 'end' });
  const mods = [['key-round', 'API-key auth'], ['gauge', 'Rate limit & quota'], ['link', 'URL check, no rewrite'], ['send', 'Dispatch to a free slot'], ['braces', 'JSON + debug headers'], ['receipt', 'Usage & request log']];
  mods.forEach((m, i) => {
    const y = 122 + i * 47;
    s += rect(ax + 12, y, aw - 24, 38, { fill: '#F4F8FC', stroke: '#DCE8F3', r: 8 });
    s += icon(m[0], ax + 22, y + 10, 18, C.blueDark) + text(ax + 50, y + 24, m[1], { size: 12.5, weight: 500 });
  });
  s += comp(390, 440, 222, 64, 'user-cog', 'Admin & Usage API', 'keys, quotas, reports');
  s += line([[344, 415], [362, 415], [362, 300], [390, 300]], { end: true, color: C.navy, width: 2.2, radius: 6 });

  // worker fleet
  const wx = 660;
  // slots
  for (let k = 2; k >= 0; k--) s += rect(wx + 14 + k * 7, 66 - k * 7 + 14, 200, 100, { fill: k ? '#E3F5EF' : C.white, stroke: '#8FD5C1', r: 10 });
  s += icon('app-window', wx + 28, 92, 20, C.tealDark) + text(wx + 56, 107, 'Warm browser slot', { size: 13.5, weight: 700 });
  s += text(wx + 28, 132, 'Chromium headless shell', { size: 11.5, fill: C.muted });
  s += text(wx + 28, 148, 'context + page + proxy', { size: 11.5, fill: C.muted });
  s += text(wx + 28, 164, 'session, kept warm', { size: 11.5, fill: C.muted });
  s += comp(wx + 246, 76, 180, 104, 'network', 'Proxy manager', 'sticky sessions\nrotate after blocks\nexit-IP checks\nhealth scores', { iconBg: C.purpleSoft, iconColor: C.purple });

  const pipe = [['mouse-pointer-click', 'Fetch', 'navigate, block check'], ['sparkles', 'Wait & expand', 'results + AI Overview'], ['link-2', 'Resolve /goto', 'in page via CDP'], ['list-checks', 'Parse', '7 parsers, registry'], ['shield-check', 'Completeness', 'any gap = error'], ['activity', 'Count', 'requests + bytes']];
  pipe.forEach((p, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = wx + 14 + col * 214, y = 210 + row * 92;
    s += comp(x, y, 196, 70, p[0], `${i + 1}. ${p[1]}`, p[2], { iconBg: C.tealSoft, iconColor: C.tealDark, size: 13 });
  });
  // flow arrows inside pipeline
  s += line([[wx + 210, 245], [wx + 228, 245]], { end: true, color: C.tealDark, width: 1.8, head: 8 });
  s += line([[wx + 324, 280], [wx + 324, 291], [wx + 112, 291], [wx + 112, 302]], { end: true, color: C.tealDark, width: 1.8, head: 8, radius: 5 });
  s += line([[wx + 210, 337], [wx + 228, 337]], { end: true, color: C.tealDark, width: 1.8, head: 8 });
  s += line([[wx + 324, 372], [wx + 324, 383], [wx + 112, 383], [wx + 112, 394]], { end: true, color: C.tealDark, width: 1.8, head: 8, radius: 5 });
  s += line([[wx + 210, 429], [wx + 228, 429]], { end: true, color: C.tealDark, width: 1.8, head: 8 });
  s += text(wx + 14, 500, 'Starts with 4 slots per worker task (2 vCPU / 4 GB); tuned by load test.', { size: 11.5, fill: C.muted });
  s += text(wx + 14, 518, 'Scripts and styles always load; images, fonts and media are skipped.', { size: 11.5, fill: C.muted });

  // gateway -> worker
  s += line([[612, 282], [640, 282], [640, 130], [674, 130]], { end: true, start: true, color: C.navy, width: 2.2, radius: 6 });
  s += lbl(640, 206, 'job', { w: 34 });

  // external
  s += comp(1126, 64, 244, 74, 'house', 'US residential proxies', 'provider gateway, per-GB billing', { iconBg: C.purpleSoft, iconColor: C.purple });
  s += comp(1126, 196, 244, 74, 'globe', 'Google Search', '/search · /async · /goto', { iconBg: C.purpleSoft, iconColor: C.purple });
  s += line([[1086, 128], [1106, 128], [1106, 101], [1126, 101]], { end: true, start: true, color: C.purple, width: 2.2, radius: 6 });
  s += line([[1248, 138], [1248, 196]], { end: true, start: true, color: C.purple, width: 2.2 });
  s += lbl(1296, 168, 'US exit IP', { w: 70, color: C.purple, stroke: '#D6CCFA' });

  // observability
  const ob = [['radar', 'OpenTelemetry', 'traces + metrics'], ['chart-line', 'Prometheus + Grafana', 'SLO dashboards'], ['scroll-text', 'CloudWatch Logs', 'JSON logs, 30 days'], ['siren', 'Alerts', 'PagerDuty · Slack']];
  ob.forEach((o, i) => { s += comp(1126, 368 + i * 51, 244, 46, o[0], o[1], o[2], { iconBg: '#FEF3C7', iconColor: C.amber, size: 12.5, iconSize: 16, shadow: false }); });

  // data
  const dy = 660;
  s += cyl(392, dy, 160, 190, 'PostgreSQL 16', { sub: 'Amazon RDS\nMulti-AZ\nkeys · requests\nresults · usage', size: 14 });
  s += cyl(566, dy, 160, 190, 'Redis 7', { sub: 'ElastiCache\njob streams\nrate limits · quotas\nproxy health', size: 14 });
  s += cyl(740, dy, 160, 190, 'Amazon S3', { sub: 'HTML + screenshot\nper request\n14-day lifecycle\nbench reports', size: 14 });
  s += hcyl(914, dy + 60, 164, 76, 'Event stream', { sub: 'Kinesis Firehose', size: 13.5 });
  // links to data
  s += line([[470, 504], [470, 660]], { end: true, start: true, color: C.slate, width: 1.8 });
  s += line([[560, 504], [560, 590], [646, 590], [646, 660]], { end: true, start: true, color: C.slate, width: 1.8, radius: 6 });
  s += line([[760, 540], [760, 610], [820, 610], [820, 660]], { end: true, color: C.slate, width: 1.8, radius: 6 });
  s += line([[1000, 540], [1000, 720]], { end: true, color: C.slate, width: 1.8 });

  // analytics
  s += comp(1126, 646, 244, 64, 'database-zap', 'S3 data lake', 'events by day, Parquet');
  s += comp(1126, 730, 244, 64, 'search-code', 'Amazon Athena', 'SQL over events');
  s += comp(1126, 814, 244, 56, 'chart-pie', 'QuickSight reports', null);
  s += line([[1078, 758], [1100, 758], [1100, 678], [1126, 678]], { end: true, color: C.slate, width: 1.8, radius: 6 });

  // control
  s += comp(30, 646, 312, 64, 'calendar-clock', 'Canary scheduler', 'EventBridge · known queries every hour', { iconBg: '#E0F2FE' });
  s += comp(30, 726, 312, 64, 'lock-keyhole', 'Secrets Manager + KMS', 'proxy credentials, key pepper', { iconBg: '#E0F2FE' });
  s += comp(30, 806, 312, 64, 'git-branch', 'GitHub Actions → ECR → ECS', 'test, build, blue/green deploy', { iconBg: '#E0F2FE' });
  s += line([[300, 646], [300, 450]], { end: true, color: C.slate, width: 1.6, dash: '5 4' });
  s += lbl(300, 520, 'test calls', { w: 66 });

  // telemetry hint
  s += line([[1092, 450], [1112, 450]], { end: true, color: C.amber, width: 1.8, dash: '5 4' });
  await L.render('05_system_architecture', W, H, s);
};

// ------------------------------------------- backend (style of the reference)
D.backend = async () => {
  const W = 1500, H = 920;
  const K = '#2B2B2B', FB = '#CFE2F3', SB = '#3E5770';
  let s = '';
  const bx = (x, y, w, h, t, o = {}) => box(x, y, w, h, t, { fill: FB, stroke: SB, sw: 1.4, r: o.r ?? 4, size: o.size || 17, weight: 700, color: '#111827', ...o });
  const arr = (pts, o = {}) => line(pts, { color: K, width: 2.6, head: 12, radius: 4, start: true, end: true, ...o });

  // client systems
  s += rect(20, 70, 176, 560, { fill: C.white, stroke: K, sw: 1.8, r: 8 });
  const cl = [['laptop', 'Client apps'], ['terminal', 'Scripts & SDKs'], ['chart-column', 'SEO / BI tools'], ['gauge', 'Benchmark runner']];
  cl.forEach((c, i) => {
    const y = 96 + i * 132;
    s += icon(c[0], 76, y, 64, K, 1.6);
    s += text(108, y + 92, c[1], { size: 14, weight: 600, anchor: 'middle', fill: '#111827' });
  });
  s += text(108, 670, 'Client', { size: 20, weight: 700, anchor: 'middle', fill: '#111827' });
  s += text(108, 696, 'Systems', { size: 20, weight: 700, anchor: 'middle', fill: '#111827' });

  // AWS boundary
  s += rect(250, 20, 1010, 880, { fill: C.white, stroke: K, sw: 1.8, r: 4 });
  s += text(1236, 58, 'Backend on AWS', { size: 22, weight: 800, anchor: 'end', fill: '#111827' });

  // 1: clients <-> ALB
  s += stack(300, 290, 130, 96, 'AWS\nALB', { fill: '#F3F4F6', stroke: '#6B7280', size: 17, weight: 600, color: '#111827', offset: 10, sub: 'TLS · WAF', subSize: 12 });
  s += arr([[198, 338], [298, 338]]); s += badge(248, 304, 1);
  // 2: ALB <-> gateway
  s += bx(506, 110, 158, 460, 'API\nGateway\nService', { size: 19, sub: '\nAPI-key auth\nrate limit & quota\nURL check\nrequest ID', subSize: 13, subColor: '#334155' });
  s += arr([[432, 338], [504, 338]]); s += badge(480, 304, 2);
  // 3: gateway <-> application API
  s += bx(722, 96, 256, 486, '', { fill: FB });
  s += text(850, 562, 'Application API', { size: 18, weight: 700, anchor: 'middle', fill: '#111827' });
  const apis = [['Admin API', 'keys · proxies · quotas'], ['Usage API', 'GET /v1/usage'], ['Health', 'GET /health'], ['Search API', 'POST /serp']];
  apis.forEach((a, i) => {
    s += box(740, 116 + i * 102, 220, 82, a[0], { fill: i === 3 ? '#E8F1FA' : '#DCEAF6', stroke: i === 3 ? '#1E3A5F' : SB, sw: i === 3 ? 2 : 1.3, r: 12, size: 17, weight: 600, color: '#111827', sub: a[1], subSize: 12.5, subColor: '#334155' });
  });
  s += arr([[666, 338], [720, 338]]); s += badge(693, 304, 3);

  // 4: search API <-> worker services
  s += stack(1044, 420, 168, 110, 'Worker\nservices', { fill: FB, stroke: SB, size: 16, weight: 600, color: '#111827', offset: 10, sub: 'fetch · parse · verify', subSize: 11.5, subColor: '#334155' });
  s += arr([[962, 475], [1042, 475]]); s += badge(1002, 441, 4);
  // 5: cache
  s += cyl(1052, 176, 158, 170, 'Cache', { fill: FB, stroke: SB, size: 20, weight: 700, color: '#111827', sub: 'Redis\nquotas · jobs\nproxy health', subSize: 12.5, subColor: '#334155', ry: 16 });
  s += arr([[1131, 348], [1131, 398]]); s += badge(1172, 372, 5);
  // 6: datastores
  s += cyl(1030, 690, 206, 180, 'Datastores', { fill: FB, stroke: SB, size: 20, weight: 700, color: '#111827', sub: 'PostgreSQL 16\nrequests · results · usage', subSize: 12.5, subColor: '#334155', ry: 18 });
  s += arr([[1131, 532], [1131, 688]]); s += badge(1172, 612, 6);
  // 7: stream pipeline
  s += hcyl(560, 640, 360, 74, 'Stream Processing\nPipeline', { fill: FB, stroke: SB, size: 17, weight: 700, color: '#111827', rx: 18 });
  s += line([[1066, 532], [1066, 677], [924, 677]], { color: K, width: 2.6, head: 12, radius: 4, end: true });
  s += badge(1030, 612, 7);
  // 8: pipeline -> S3, Athena, datastores
  s += bx(560, 800, 150, 64, 'AWS S3', { fill: '#F3F4F6', stroke: '#6B7280', size: 16, weight: 600, sub: 'artifacts · events', subSize: 11.5 });
  s += bx(760, 800, 150, 64, 'Athena', { fill: '#F3F4F6', stroke: '#6B7280', size: 16, weight: 600, sub: 'analytics SQL', subSize: 11.5 });
  s += line([[690, 716], [640, 796]], { color: K, width: 2.6, head: 12, end: true });
  s += line([[745, 716], [825, 796]], { color: K, width: 2.6, head: 12, end: true });
  s += line([[800, 716], [1026, 790]], { color: K, width: 2.6, head: 12, end: true });
  s += badge(728, 770, 8);

  // 9: out to proxies and Google
  s += bx(1300, 404, 180, 88, 'US Residential\nProxies', { fill: '#EDE9FE', stroke: '#6D28D9', size: 16, weight: 700 });
  s += bx(1300, 590, 180, 88, 'Google\nSearch', { fill: C.white, stroke: K, size: 17, weight: 700 });
  s += arr([[1230, 448], [1298, 448]]); s += badge(1281, 414, 9);
  s += arr([[1390, 494], [1390, 588]]);
  s += text(1390, 716, 'outside AWS', { size: 13, fill: C.muted, anchor: 'middle', style: 'italic' });
  // 10: canary + monitoring
  s += bx(290, 660, 170, 66, 'Canary', { fill: '#F3F4F6', stroke: '#6B7280', size: 16, weight: 600, sub: 'hourly test queries', subSize: 11.5 });
  s += bx(290, 790, 170, 66, 'Monitoring', { fill: '#F3F4F6', stroke: '#6B7280', size: 16, weight: 600, sub: 'Grafana · alerts', subSize: 11.5 });
  s += line([[365, 658], [365, 390]], { color: K, width: 2, head: 11, end: true, dash: '7 5' });
  s += line([[558, 700], [520, 700], [520, 823], [462, 823]], { color: K, width: 2, head: 11, end: true, dash: '7 5', radius: 4 });
  s += badge(398, 600, 10, { size: 13 });
  await L.render('06_backend_architecture', W, H, s);
};

// ------------------------------------------------------------ request lifecycle
D.lifecycle = async () => {
  const W = 1000, H = 990;
  let s = '';
  const lanes = [['Client', 95, 'laptop'], ['SERP Gateway', 285, 'server'], ['Browser worker', 490, 'app-window'], ['US proxy', 700, 'house'], ['Google', 900, 'globe']];
  s += rect(645, 20, 110, 628, { fill: '#F5F3FF', stroke: '#DDD6FE', r: 12 });
  lanes.forEach(([n, x, ic]) => {
    const px = n === 'US proxy';
    s += rect(x - 80, 24, 160, 48, { fill: px ? '#EDE9FE' : C.navy, r: 10 });
    const tw = n.length * 8.1 + 30;
    s += icon(ic, x - tw / 2, 37, 20, px ? C.purple : '#fff', 2);
    s += text(x - tw / 2 + 28, 53, n, { size: 14, weight: 700, fill: px ? C.purple : '#fff' });
    if (!px) s += `<line x1="${x}" y1="72" x2="${x}" y2="640" stroke="${C.faint}" stroke-width="1.5" stroke-dasharray="5 5"/>`;
  });
  s += rect(277, 96, 16, 500, { fill: C.lightBlue, stroke: C.blue, r: 3, sw: 1 });
  s += rect(482, 200, 16, 350, { fill: C.tealSoft, stroke: C.teal, r: 3, sw: 1 });
  const lab = (n, x, y, label, sub, o = {}) =>
    badge(x + 11, y - 13, n, { r: 11, size: 11.5 }) +
    text(x + 28, y - 8, label, { size: 12.5, weight: 600, fill: o.tcolor || C.ink }) +
    (sub ? text(x + 28, y + 16, sub, { size: 11.5, fill: C.muted }) : '');
  const msg = (n, y, x1, x2, label, sub, o = {}) =>
    line([[x1, y], [x2, y]], { end: true, color: o.color || C.ink, width: 2, head: 9, dash: o.dash }) +
    lab(n, Math.min(x1, x2) + 8, y, label, sub, o);
  const self = (n, x, y, label, sub) =>
    line([[x, y - 10], [x + 36, y - 10], [x + 36, y + 12], [x + 2, y + 12]], { end: true, color: C.ink, width: 1.8, head: 8, radius: 6 }) +
    badge(x + 56, y - 2, n, { r: 11, size: 11.5 }) +
    text(x + 74, y + 3, label, { size: 12.5, weight: 600 }) +
    text(x + 74, y + 19, sub, { size: 11.5, fill: C.muted });
  s += msg(1, 112, 95, 277, 'POST /serp', 'url, results, country');
  s += self(2, 293, 168, 'Check key, quota, URL', 'bad URL → 400, nothing fetched');
  s += msg(3, 226, 293, 482, 'job → warm slot', 'via Redis Streams');
  s += msg(4, 280, 498, 900, 'GET /search — URL exactly as the client sent it');
  s += msg(5, 330, 900, 498, 'HTML + scripts', 'early check: CAPTCHA? consent wall?');
  s += msg(6, 390, 498, 900, '/async follow-ups: the AI Overview streams in', 'clicks "Show more" / "Show all" and checks each click worked');
  s += msg(7, 450, 498, 900, '/goto lookups (4–18 per page), 16 at a time', 'reads the 302 Location only; the destination site is never visited');
  s += self(8, 498, 508, 'Parse · completeness gate', 'count Google requests + bytes');
  s += msg(9, 568, 482, 293, 'result + counters');
  s += msg(10, 608, 277, 95, 'JSON + debug headers');
  s += msg(11, 636, 293, 610, 'after reply: event, DB row, proof → S3', null, { dash: '6 4', color: C.muted, tcolor: C.muted });
  s += text(700, 612, 'every Google call', { size: 11, fill: C.purple, anchor: 'middle', weight: 600 });
  s += text(700, 626, 'leaves from here', { size: 11, fill: C.purple, anchor: 'middle', weight: 600 });

  // time budget
  const by = 690;
  s += text(40, by, 'TIME BUDGET FOR ONE PAGE', { size: 12, weight: 700, fill: C.muted, ls: 1.2 });
  s += text(960, by, 'target, not yet measured · P95 ≤ 2,000 ms', { size: 12, fill: C.muted, anchor: 'end' });
  const segs = [['Gateway + dispatch', 30, '#94A3B8', '1–3'], ['Page load via proxy', 900, C.blue, '4'], ['Results + checks', 200, '#7DB9D8', '5'], ['AI Overview settle + expand', 500, C.teal, '6'], ['/goto lookups', 250, C.purple, '7'], ['Parse + reply', 120, C.navy, '8–10']];
  const x0 = 40, span = 920, scale = span / 2000;
  let cx = x0;
  segs.forEach((g, i) => {
    const w = g[1] * scale;
    s += `<rect x="${cx}" y="${by + 24}" width="${w}" height="40" fill="${g[2]}" ${i === 0 ? 'rx="6"' : ''}/>`;
    if (w > 70) s += text(cx + w / 2, by + 49, `${g[1]} ms`, { size: 13, weight: 700, fill: '#fff', anchor: 'middle' });
    // label below with leader
    const lx = cx + w / 2, row = i % 2;
    s += `<line x1="${lx}" y1="${by + 66}" x2="${lx}" y2="${by + 84 + row * 40}" stroke="${g[2]}" stroke-width="1.5"/>`;
    s += text(lx, by + 98 + row * 40, g[0] + (w > 70 ? '' : ` · ${g[1]} ms`), { size: 12, weight: 600, anchor: i === 0 ? 'start' : i === segs.length - 1 ? 'end' : 'middle', fill: C.ink });
    s += text(lx, by + 113 + row * 40, `step ${g[3]}`, { size: 11, fill: C.muted, anchor: i === 0 ? 'start' : i === segs.length - 1 ? 'end' : 'middle' });
    cx += w;
  });
  [0, 500, 1000, 1500, 2000].forEach((t) => {
    const x = x0 + t * scale;
    s += `<line x1="${x}" y1="${by + 16}" x2="${x}" y2="${by + 22}" stroke="${C.faint}" stroke-width="1.2"/>`;
    s += text(x, by + 12, `${t}`, { size: 10.5, fill: C.faint, anchor: t === 0 ? 'start' : t === 2000 ? 'end' : 'middle' });
  });
  s += rect(40, by + 172, 920, 108, { fill: C.amberSoft, stroke: '#FCD34D', r: 10 });
  s += icon('triangle-alert', 56, by + 188, 20, C.amber);
  s += text(86, by + 203, 'The AI Overview is the risk to P95.', { size: 13.5, weight: 700, fill: '#78350F' });
  s += text(86, by + 223, 'Google streams it after the page loads, so it can take seconds on its own. Plain queries skip step 6 and', { size: 12.5, fill: '#78350F' });
  s += text(86, by + 241, 'return early. We will not return a half-loaded overview to save time: it becomes aio_incomplete instead.', { size: 12.5, fill: '#78350F' });
  s += text(86, by + 259, 'The smoke test measures this first (see Delivery plan).', { size: 12.5, fill: '#78350F' });
  await L.render('07_request_lifecycle', W, H, s);
};

// ------------------------------------------------------------- outcome tree
D.outcomes = async () => {
  const W = 1000, H = 1010;
  let s = '';
  const cx = 250, dw = 330, dh = 92, gap = 118, y0 = 100;
  s += rect(cx - 110, 20, 220, 44, { fill: C.navy, r: 22 });
  s += text(cx, 48, 'Request arrives', { size: 15, weight: 700, fill: '#fff', anchor: 'middle' });
  const ds = [
    ['Is it a valid Google\nsearch URL?', 'No', 'Yes', '400', 'invalid_url', 'Rejected up front. Nothing is fetched.'],
    ['Did the page load\nbefore the deadline?', 'No', 'Yes', '504 / 502', 'timeout · network_error', 'The only two errors that may be retried.'],
    ['Is it a CAPTCHA or\n"unusual traffic" page?', 'Yes', 'No', '429', 'blocked_captcha', 'Session dropped. Never retried on the same IP.'],
    ['Is it a cookie\nconsent wall?', 'Yes', 'No', '502', 'consent_wall', 'Next request gets a fresh session.'],
    ['Results visible, at least\none organic result?', 'No', 'Yes', '502', 'degraded_page', 'JS notice, basic HTML page or empty results.'],
    ['AI Overview shown? Then is it\nfully loaded with every source?', 'No', 'Yes / none', '502', 'aio_incomplete', 'A half-finished overview is never returned.'],
    ['Does every result link\nhave its real destination?', 'No', 'Yes', '502', 'parse_error', 'Links are never guessed from the breadcrumb.'],
  ];
  s += line([[cx, 64], [cx, y0]], { end: true, color: C.ink, width: 2, head: 9 });
  ds.forEach((d, i) => {
    const y = y0 + i * gap, my = y + dh / 2;
    s += `<polygon points="${cx},${y} ${cx + dw / 2},${my} ${cx},${y + dh} ${cx - dw / 2},${my}" fill="${C.lightBlue}" stroke="${C.blue}" stroke-width="1.8"/>`;
    s += text(cx, my, d[0], { size: 13, weight: 600, anchor: 'middle', valign: 'middle', lh: 16 });
    // exit to error
    s += line([[cx + dw / 2, my], [520, my]], { end: true, color: C.red, width: 2, head: 9 });
    s += text(cx + dw / 2 + 14, my - 8, d[1], { size: 12, weight: 700, fill: C.red });
    s += rect(522, my - 32, 458, 64, { fill: '#FFF7ED', stroke: C.redLine, r: 12 });
    s += rect(534, my - 20, 84, 40, { fill: C.red, r: 8 });
    s += text(576, my + 5, d[3], { size: d[3].length > 4 ? 13 : 16, weight: 800, fill: '#fff', anchor: 'middle' });
    s += text(632, my - 4, d[4], { size: 14, weight: 700, fill: '#7C2D12', family: 'DejaVu Sans Mono, monospace' });
    s += text(632, my + 16, d[5], { size: 12, fill: '#9A3412' });
    // continue down
    s += line([[cx, y + dh], [cx, y + gap]], { end: true, color: C.green, width: 2, head: 9 });
    s += text(cx + 10, y + dh + 17, d[2], { size: 12, weight: 700, fill: C.green });
  });
  const fy = y0 + ds.length * gap;
  s += rect(cx - 200, fy, 400, 70, { fill: C.greenSoft, stroke: '#4ADE80', r: 14, sw: 2 });
  s += rect(cx - 186, fy + 15, 84, 40, { fill: C.green, r: 8 });
  s += text(cx - 144, fy + 41, '200', { size: 17, weight: 800, fill: '#fff', anchor: 'middle' });
  s += text(cx - 88, fy + 31, 'Valid result', { size: 16, weight: 700, fill: '#14532D' });
  s += text(cx - 88, fy + 51, 'every field read in full, nothing guessed', { size: 12, fill: '#166534' });
  s += text(522, fy + 30, 'On any error: results = [ ], plus error and error_message.', { size: 12.5, fill: C.muted });
  s += text(522, fy + 50, 'Debug headers and the saved page explain what happened.', { size: 12.5, fill: C.muted });
  await L.render('08_outcomes', W, H, s);
};

// ------------------------------------------------------------- AWS deployment
D.deployment = async () => {
  const W = 1400, H = 880;
  let s = '';
  // internet column
  s += zone(16, 16, 164, 848, 'INTERNET');
  s += comp(26, 64, 144, 62, 'users', 'Clients', 'HTTPS + API key', { size: 13 });
  s += comp(26, 166, 144, 62, 'waypoints', 'Route 53', 'api.example.com', { size: 13 });
  s += comp(26, 268, 144, 62, 'shield', 'WAF + Shield', 'rate & IP rules', { size: 13 });
  s += line([[98, 126], [98, 166]], { end: true, color: C.navy, width: 2 });
  s += line([[98, 228], [98, 268]], { end: true, color: C.navy, width: 2 });
  s += comp(26, 452, 144, 70, 'house', 'Proxy provider', 'US residential', { size: 13, iconBg: C.purpleSoft, iconColor: C.purple });
  s += comp(26, 580, 144, 62, 'globe', 'Google', 'www.google.com', { size: 13, iconBg: C.purpleSoft, iconColor: C.purple });
  s += line([[98, 522], [98, 580]], { end: true, start: true, color: C.purple, width: 2 });

  // region
  s += zone(196, 16, 1188, 848, 'AWS REGION · us-east-1', null, { fill: '#FBFCFE', stroke: '#94A3B8', color: C.navy });
  s += zone(212, 52, 832, 652, 'VPC · 10.0.0.0/16', null, { fill: C.white, stroke: C.blue, color: C.blueDark });
  s += text(434, 88, 'Availability zone A', { size: 13, weight: 700, fill: C.blueDark, anchor: 'middle' });
  s += text(840, 88, 'Availability zone B', { size: 13, weight: 700, fill: C.blueDark, anchor: 'middle' });
  const bands = [['PUBLIC SUBNETS', 98, 100, '#EFF6FF'], ['PRIVATE · API', 206, 96, '#F0F9FF'], ['PRIVATE · BROWSER WORKERS', 310, 164, '#F0FDF9'], ['PRIVATE · DATA', 482, 210, '#F8FAFC']];
  bands.forEach(([t, y, h, f]) => {
    s += rect(224, y, 808, h, { fill: f, stroke: '#E2E8F0', r: 10 });
    s += text(236, y + 16, t, { size: 10.5, weight: 700, fill: C.muted, ls: 1 });
  });
  s += `<line x1="636" y1="96" x2="636" y2="696" stroke="${C.faint}" stroke-width="1.4" stroke-dasharray="6 5"/>`;
  [236, 648].forEach((x0, k) => {
    s += comp(x0, 124, 176, 60, 'split', 'ALB node', 'TLS ends here', { size: 13 });
    s += comp(x0 + 192, 124, 176, 60, 'arrow-up-right', 'NAT gateway', 'egress only', { size: 13 });
    s += comp(x0, 230, 262, 60, 'server', 'SERP Gateway tasks', 'Fargate · auto-scale 1 → 5', { size: 13 });
    s += rect(x0, 334, 368, 126, { fill: C.white, stroke: '#A7E3D3', r: 10, shadow: true });
    s += icon('cpu', x0 + 12, 346, 20, C.tealDark) + text(x0 + 42, 361, 'Browser workers', { size: 13.5, weight: 700 });
    s += text(x0 + 360, 361, 'EC2 c7i.xlarge', { size: 11.5, fill: C.muted, anchor: 'end' });
    for (let j = 0; j < 4; j++) {
      s += rect(x0 + 12 + j * 88, 374, 80, 44, { fill: C.tealSoft, stroke: '#8FD5C1', r: 8 });
      s += icon('app-window', x0 + 20 + j * 88, 386, 18, C.tealDark) + text(x0 + 44 + j * 88, 401, `slot ${j + 1}`, { size: 11.5, weight: 600, fill: C.tealDark });
    }
    s += text(x0 + 12, 444, 'Auto Scaling group · scale on busy slots · 1 → N per AZ', { size: 11.5, fill: C.muted });
    // vertical flows
    s += line([[x0 + 130, 184], [x0 + 130, 230]], { end: true, color: C.navy, width: 1.8, head: 8 });
    s += line([[x0 + 225, 290], [x0 + 225, 334]], { end: true, color: C.navy, width: 1.8, head: 8 });
    s += line([[x0 + 310, 334], [x0 + 310, 184]], { end: true, color: C.purple, width: 1.8, head: 8 });
    s += text(x0 + 318, 252, 'egress', { size: 10.5, fill: C.purple, weight: 600 });
    s += text(x0 + 318, 266, 'via NAT', { size: 10.5, fill: C.purple, weight: 600 });
  });
  // data tier
  s += cyl(250, 504, 160, 160, 'Redis 7', { sub: 'primary', size: 14 });
  s += cyl(440, 504, 170, 160, 'PostgreSQL 16', { sub: 'RDS primary', size: 14 });
  s += cyl(662, 504, 170, 160, 'PostgreSQL 16', { sub: 'RDS standby', size: 14 });
  s += cyl(858, 504, 160, 160, 'Redis 7', { sub: 'replica', size: 14 });
  s += line([[612, 584], [660, 584]], { end: true, start: true, color: C.blueDark, width: 1.8, head: 8, dash: '5 4' });
  s += text(636, 574, 'sync', { size: 10.5, fill: C.blueDark, anchor: 'middle', weight: 600 });
  s += line([[330, 666], [330, 684], [938, 684], [938, 666]], { end: true, color: C.blueDark, width: 1.6, head: 8, dash: '5 4', radius: 5 });
  s += text(760, 680, 'async replica', { size: 10.5, fill: C.blueDark, weight: 600 });

  // edge -> ALB, workers -> proxy
  s += line([[170, 299], [190, 299], [190, 154], [236, 154]], { end: true, color: C.navy, width: 2.2, radius: 6 });
  s += line([[236, 420], [204, 420], [204, 487], [170, 487]], { end: true, color: C.purple, width: 2.2, radius: 6 });

  // regional services
  s += zone(1060, 52, 312, 652, 'REGIONAL SERVICES', 'reached through VPC endpoints', { fill: C.white, stroke: '#CBD5E1' });
  const rs = [['hard-drive', 'Amazon S3', 'proof pages, events, reports'], ['package', 'Amazon ECR', 'container images'], ['lock-keyhole', 'Secrets Manager + KMS', 'proxy creds, key pepper'], ['chart-line', 'CloudWatch + Grafana', 'logs, metrics, alarms'], ['radio-tower', 'Kinesis Firehose', 'request events → S3'], ['calendar-clock', 'EventBridge', 'hourly canary, nightly jobs']];
  rs.forEach((r, i) => { s += comp(1074, 108 + i * 98, 284, 80, r[0], r[1], r[2], { size: 13.5 }); });

  // CI/CD strip
  s += zone(212, 720, 1160, 132, 'DELIVERY PIPELINE', null, { fill: C.white, stroke: '#CBD5E1' });
  const ci = [['git-branch', 'GitHub', 'pull request'], ['list-checks', 'GitHub Actions', 'tests + real-page fixtures'], ['container', 'Docker build', 'API + worker images'], ['package', 'Amazon ECR', 'signed, scanned'], ['refresh-cw', 'ECS deploy', 'blue/green, auto rollback'], ['layers', 'Terraform', 'infra as code, per env']];
  ci.forEach((c, i) => {
    const x = 228 + i * 190;
    s += comp(x, 758, 172, 70, c[0], c[1], c[2], { size: 13, iconBg: '#E0F2FE' });
    if (i < ci.length - 1) s += line([[x + 172, 793], [x + 190, 793]], { end: true, color: C.navy, width: 1.8, head: 8 });
  });
  await L.render('12_deployment', W, H, s);
};

// --------------------------------------------------------------- tech stack map
D.stack = async () => {
  const W = 1000;
  const rows = [
    ['plug', 'Client access', [['REST + JSON', 1], ['X-API-Key auth', 1], ['OpenAPI 3.1 docs', 0], ['Python & Node SDKs', 0], ['Webhooks for batch jobs', 0]]],
    ['shield', 'Edge & security', [['Route 53', 0], ['AWS WAF + Shield', 0], ['Application Load Balancer', 0], ['ACM certificates, TLS 1.2+', 0]]],
    ['server', 'API service', [['Python 3.12', 1], ['FastAPI', 1], ['Uvicorn', 1], ['Pydantic v2', 1], ['pydantic-settings', 1]]],
    ['app-window', 'Browser & parsing', [['Playwright', 1], ['Chromium headless shell', 1], ['Chrome DevTools Protocol', 1], ['selectolax', 1], ['httpx', 1]]],
    ['send', 'Messaging', [['Redis Streams (job dispatch)', 0], ['Kinesis Data Firehose (events)', 0]]],
    ['database', 'Data', [['PostgreSQL 16 on RDS', 0], ['Redis 7 on ElastiCache', 0], ['Amazon S3', 0], ['Athena + Parquet', 0]]],
    ['container', 'Compute & infra', [['Docker', 0], ['Amazon ECS', 0], ['Fargate (API)', 0], ['EC2 c7i (workers)', 0], ['Terraform', 0]]],
    ['git-branch', 'Delivery', [['GitHub Actions', 0], ['Amazon ECR', 0], ['ECS blue/green', 0], ['Dependabot', 0]]],
    ['activity', 'Observability', [['OpenTelemetry', 0], ['Managed Prometheus', 0], ['Grafana', 0], ['CloudWatch Logs', 0], ['Sentry', 0], ['PagerDuty', 0]]],
    ['list-checks', 'Quality', [['pytest · 183 tests', 1], ['16 real Google pages', 1], ['Local Google stand-in', 1], ['Benchmark runner', 1], ['k6 · Ruff · mypy', 0]]],
  ];
  const top = 58, rh = 66;
  const H = top + rows.length * rh + 10;
  let s = '';
  s += pill(20, 16, 'In use today (built and tested)', { fill: C.tealSoft, stroke: '#5FD0B8', color: C.tealDark, icon: 'circle-check', size: 12.5, weight: 600 });
  s += pill(290, 16, 'Added for production', { fill: C.white, stroke: '#93B8D6', color: C.blueDark, icon: 'circle-plus', size: 12.5, weight: 600 });
  rows.forEach((r, i) => {
    const y = top + i * rh;
    s += rect(16, y, 968, rh - 8, { fill: i % 2 ? C.white : C.softer, stroke: '#E2E8F0', r: 10 });
    s += `<rect x="28" y="${y + 13}" width="32" height="32" rx="8" fill="${C.navy}"/>` + icon(r[0], 35, y + 20, 18, '#fff', 2);
    s += text(72, y + 34, r[1], { size: 14.5, weight: 700 });
    s += L.pillRow(232, y + 16, r[2].map(([t, now]) => ({ label: t, fill: now ? C.tealSoft : C.white, stroke: now ? '#5FD0B8' : '#93B8D6', color: now ? C.tealDark : C.blueDark })), { maxW: 748, gap: 7, size: 12.5, weight: 600, h: 27, pad: 11 });
  });
  await L.render('11_tech_stack', W, H, s);
};

// --------------------------------------------------------------------- roadmap
D.roadmap = async () => {
  const W = 1000, H = 610;
  let s = '';
  const lx = 20, tx = 300, tw = 680, weeks = 12, ww = tw / weeks;
  const hy = 70;
  s += rect(lx, 14, W - 40, 40, { fill: C.greenSoft, stroke: '#86EFAC', r: 10 });
  s += icon('circle-check', lx + 12, 24, 20, C.green) + text(lx + 42, 39, 'Already done: API, 7 parsers, completeness gate, proxy support, benchmark tool, 183 tests', { size: 13, weight: 600, fill: '#14532D' });
  for (let i = 0; i < weeks; i++) {
    const x = tx + i * ww;
    s += rect(x + 1, hy, ww - 2, 26, { fill: i % 2 ? C.soft : '#E8EEF5', r: 5 });
    s += text(x + ww / 2, hy + 18, `W${i + 1}`, { size: 12, weight: 700, fill: C.slate, anchor: 'middle' });
  }
  const rows = [
    ['Live proxy smoke test', 'single session, ≤ 23 page loads', 1, 1, C.purple],
    ['Tune for the targets', 'cache-safe blocking, early exits', 2, 3, C.teal],
    ['Production platform', 'gateway/worker split, Redis, IaC', 3, 7, C.blue],
    ['Data layer & usage API', 'PostgreSQL, S3 proof, rollups', 4, 7, '#5B9BD5'],
    ['Monitoring & hourly canary', 'dashboards, alerts, drift checks', 6, 8, '#D97706'],
    ['Load & acceptance test', 'benchmark at scale, sign-off', 8, 9, '#DC6B5E'],
    ['Go-live + hypercare', 'cut-over in W10, then daily reviews', 10, 12, C.green],
    ['Client portal (optional)', 'keys, usage, invoices', 9, 12, '#94A3B8'],
  ];
  const ry = hy + 40, rh = 50;
  rows.forEach((r, i) => {
    const y = ry + i * rh;
    s += `<line x1="${lx}" y1="${y + rh - 4}" x2="${W - 20}" y2="${y + rh - 4}" stroke="#EEF2F6" stroke-width="1"/>`;
    s += text(lx, y + 20, r[0], { size: 14, weight: 700 });
    s += text(lx, y + 37, r[1], { size: 11.5, fill: C.muted });
    const x = tx + (r[2] - 1) * ww + 3, w = (r[3] - r[2] + 1) * ww - 6;
    s += rect(x, y + 8, w, 28, { fill: r[4], r: 8, dash: i === 7 ? '5 4' : null, opacity: i === 7 ? 0.9 : null });
    s += text(x + w / 2, y + 27, `${r[3] - r[2] + 1} wk${r[3] - r[2] ? 's' : ''}`, { size: 12, weight: 700, fill: '#fff', anchor: 'middle' });
  });
  // milestones
  const my = ry + rows.length * rh + 22;
  s += text(lx, my + 5, 'Milestones', { size: 14, weight: 700 });
  const ms = [[1, 'M1', 'Smoke test\nreport'], [3, 'M2', 'Targets met on\nthe benchmark'], [7, 'M3', 'Staging\nready'], [9, 'M4', 'Acceptance\nsign-off'], [10, 'GO', 'Go-live']];
  ms.forEach(([wk, id, t]) => {
    const x = tx + wk * ww;
    s += `<line x1="${x}" y1="${hy + 28}" x2="${x}" y2="${my - 12}" stroke="${id === 'GO' ? C.green : C.faint}" stroke-width="1.3" stroke-dasharray="4 4"/>`;
    s += `<polygon points="${x},${my - 12} ${x + 12},${my} ${x},${my + 12} ${x - 12},${my}" fill="${id === 'GO' ? C.green : C.navy}"/>`;
    s += text(x, my + 32, id, { size: 12, weight: 800, fill: id === 'GO' ? C.green : C.navy, anchor: 'middle' });
    s += text(x, my + 48, t, { size: 11, fill: C.muted, anchor: 'middle', lh: 14 });
  });
  await L.render('13_roadmap', W, H, s);
};

module.exports = D;

if (require.main === module) {
  (async () => {
    const names = process.argv.slice(2);
    for (const n of names.length ? names : Object.keys(D)) await D[n]();
    await L.done();
  })();
}
