/* Financial Hub 儀表板：讀取 data/*.json 與 reports/*.md，純前端、無建置步驟。 */
(() => {
'use strict';
const SVG = 'http://www.w3.org/2000/svg';
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const isNum = x => typeof x === 'number' && isFinite(x);
const fmt = (x, nd = 2) => isNum(x) ? x.toLocaleString('en-US', { minimumFractionDigits: nd, maximumFractionDigits: nd }) : '—';
const signed = (x, nd = 2, suf = '') => isNum(x) ? (x >= 0 ? '+' : '−') + fmt(Math.abs(x), nd) + suf : '—';
const peFmt = x => !isNum(x) ? '—' : (x <= 0 || x > 500) ? 'n/m' : fmt(x, 1);
const compact = mc => !isNum(mc) ? '—' : mc >= 1e12 ? (mc / 1e12).toFixed(2) + 'T' : mc >= 1e9 ? (mc / 1e9).toFixed(1) + 'B' : mc >= 1e6 ? (mc / 1e6).toFixed(0) + 'M' : String(Math.round(mc));
const dir = x => !isNum(x) ? '' : x > 0 ? 'up' : x < 0 ? 'down' : '';
const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const RANGES = { '1M': 22, '3M': 64, '6M': 128, '1Y': 252, '2Y': 100000 };
const CHARTS = [];
const S = { live: false, universe: null, universeLoading: null };

/* ------------------------------------------------------------ 小工具 */
function parseCsv(text) {
  if (!text) return [];
  const lines = text.replace(/\r/g, '').split('\n').filter(Boolean);
  if (lines.length < 2) return [];
  const hdr = lines[0].split(',');
  return lines.slice(1).map(l => { const p = l.split(','); const o = {}; hdr.forEach((h, i) => { o[h] = p[i] === '' || p[i] === undefined ? null : p[i]; }); return o; });
}
const num = v => (v === null || v === undefined || v === '') ? null : (isNaN(+v) ? null : +v);
function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v; else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v); }
  for (const c of children) { if (c === null || c === undefined) continue; e.append(c.nodeType ? c : document.createTextNode(String(c))); }
  return e;
}
function tile(label, value, delta, note, opts = {}) {
  const t = el('div', { class: 'tile' + (opts.hero ? ' hero' : '') });
  t.append(el('div', { class: 'label', text: label }), el('div', { class: 'value', text: value }));
  if (delta !== undefined && delta !== null) t.append(el('div', { class: 'delta ' + (opts.deltaClass || ''), text: delta }));
  if (note) t.append(el('div', { class: 'note', text: note }));
  return t;
}
function niceTicks(lo, hi, n = 5) {
  if (!(hi > lo)) { hi = lo + 1; lo = lo - 1; }
  const span = hi - lo; const step0 = span / n; const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const err = step0 / mag; const step = (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1) * mag;
  const start = Math.ceil(lo / step) * step; const ticks = [];
  for (let v = start; v <= hi + 1e-9; v += step) ticks.push(+v.toFixed(10));
  return ticks;
}
function seriesColor(i) { return cssVar(['--s1', '--s2', '--s3', '--div-neg', '--muted'][i] || '--muted'); }
function heat(pct, center = 50, scale = 50) {
  if (!isNum(pct)) return '';
  const t = (pct - center) / scale; const a = 0.08 + 0.55 * Math.min(1, Math.abs(t));
  const hex = cssVar(t < 0 ? '--div-neg' : '--div-pos');
  const r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
  return `background: rgba(${r},${g},${b},${a.toFixed(2)})`;
}

/* ------------------------------------------------------------ 折線圖（SVG，含十字線與 tooltip） */
function mk(tag, attrs) { const e = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; }
class LineChart {
  constructor(container, opts = {}) {
    this.el = container; this.el.classList.add('chart');
    this.opts = Object.assign({ height: 260, yFmt: v => fmt(v, 1), range: '1Y', bands: [], area: false, yMin: null, yMax: null }, opts);
    this.series = []; this.linked = []; this.hoverDate = null;
    this.legendEl = el('div', { class: 'legend' });
    this.svg = document.createElementNS(SVG, 'svg');
    this.tip = el('div', { class: 'tooltip' });
    this.el.append(this.legendEl, this.svg, this.tip);
    this.ro = new ResizeObserver(() => this.render()); this.ro.observe(this.el);
    CHARTS.push(this);
  }
  setSeries(series) { this.series = (series || []).filter(s => s && s.dates && s.dates.length); this.render(); }
  setRange(r) { this.opts.range = r; this.render(); }
  visibleDates() {
    const set = new Set(); this.series.forEach(s => s.dates.forEach(d => set.add(d)));
    const all = Array.from(set).sort(); const n = RANGES[this.opts.range] || 100000;
    return all.slice(-n);
  }
  render() {
    const W = Math.max(280, this.el.clientWidth || 600), H = this.opts.height;
    const m = { t: 14, r: 58, b: 26, l: 46 }; const pw = W - m.l - m.r, ph = H - m.t - m.b;
    const svg = this.svg; while (svg.firstChild) svg.removeChild(svg.firstChild);
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('width', W); svg.setAttribute('height', H);
    const dates = this.visibleDates(); this.dates = dates;
    this.legendEl.textContent = '';
    if (!dates.length) { const t = mk('text', { x: W / 2, y: H / 2, class: 'tick', 'text-anchor': 'middle' }); t.textContent = '尚無資料'; svg.append(t); return; }
    const maps = this.series.map(s => { const mp = new Map(); s.dates.forEach((d, i) => { if (isNum(s.values[i])) mp.set(d, s.values[i]); }); return mp; });
    this.maps = maps;
    let lo = Infinity, hi = -Infinity;
    maps.forEach(mp => dates.forEach(d => { const v = mp.get(d); if (isNum(v)) { if (v < lo) lo = v; if (v > hi) hi = v; } }));
    (this.opts.bands || []).forEach(b => { if (b.y < lo) lo = b.y; if (b.y > hi) hi = b.y; });
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    const pad = (hi - lo) * 0.06 || Math.abs(hi) * 0.05 || 1; lo -= pad; hi += pad;
    if (isNum(this.opts.yMin)) lo = this.opts.yMin; if (isNum(this.opts.yMax)) hi = this.opts.yMax;
    const n = dates.length; const xs = i => m.l + (n === 1 ? pw / 2 : i / (n - 1) * pw); const ys = v => m.t + (hi - v) / (hi - lo) * ph;
    this.xs = xs; this.ys = ys; this.W = W; this.H = H; this.m = m;
    niceTicks(lo, hi, 5).forEach(v => {
      svg.append(mk('line', { x1: m.l, x2: W - m.r, y1: ys(v), y2: ys(v), class: 'grid-line' }));
      const t = mk('text', { x: m.l - 6, y: ys(v) + 4, class: 'tick', 'text-anchor': 'end' }); t.textContent = this.opts.yFmt(v); svg.append(t);
    });
    svg.append(mk('line', { x1: m.l, x2: W - m.r, y1: m.t + ph, y2: m.t + ph, class: 'axis-line' }));
    const minGap = 58; let lastX = -Infinity; let lastMonth = null, lastYear = null;
    const labelEvery = n <= 70 ? Math.max(1, Math.ceil(n / Math.max(2, Math.floor(pw / 72)))) : null;
    dates.forEach((d, i) => {
      let label = null; const yy = d.slice(0, 4), mm = +d.slice(5, 7);
      if (labelEvery) { if (i % labelEvery === 0) label = `${mm}/${+d.slice(8, 10)}`; }
      else if (mm !== lastMonth) { label = (yy !== lastYear) ? `${yy}/${mm}` : `${mm}月`; lastMonth = mm; lastYear = yy; }
      if (!label) return;
      const x = xs(i); if (x - lastX < minGap || x > W - m.r - 14) return;
      lastX = x; const t = mk('text', { x, y: H - 8, class: 'tick', 'text-anchor': i === 0 ? 'start' : 'middle' }); t.textContent = label; svg.append(t);
    });
    (this.opts.bands || []).forEach(b => {
      svg.append(mk('line', { x1: m.l, x2: W - m.r, y1: ys(b.y), y2: ys(b.y), class: 'band' }));
      const t = mk('text', { x: m.l + 4, y: ys(b.y) - 4, class: 'band-label' }); t.textContent = b.label || String(b.y); svg.append(t);
    });
    const ends = [];
    this.series.forEach((s, si) => {
      const color = s.color || seriesColor(si); let d = '', pen = false, lastPt = null;
      dates.forEach((dt, i) => { const v = maps[si].get(dt); if (isNum(v)) { d += (pen ? 'L' : 'M') + xs(i).toFixed(1) + ' ' + ys(v).toFixed(1); pen = true; lastPt = [xs(i), ys(v), v]; } else pen = false; });
      if (!d) return;
      if (this.opts.area && this.series.length === 1) {
        let a = '', first = null, last = null; dates.forEach((dt, i) => { const v = maps[si].get(dt); if (isNum(v)) { if (first === null) first = xs(i); last = xs(i); a += (a ? 'L' : 'M') + xs(i).toFixed(1) + ' ' + ys(v).toFixed(1); } });
        const baseY = (lo < 0 && hi > 0) ? ys(0) : m.t + ph;  // 跨越零軸的序列以零軸為底
        if (a) svg.append(mk('path', { d: a + `L${last.toFixed(1)} ${baseY.toFixed(1)}L${first.toFixed(1)} ${baseY.toFixed(1)}Z`, class: 'area', fill: color }));
      }
      svg.append(mk('path', { d, class: 'line', stroke: color }));
      const pts = dates.map((dt, i) => [i, maps[si].get(dt)]).filter(p => isNum(p[1]));
      if (pts.length <= 3) pts.forEach(p => svg.append(mk('circle', { cx: xs(p[0]), cy: ys(p[1]), r: 4.5, fill: color, stroke: cssVar('--surface-1'), 'stroke-width': 2 })));
      if (lastPt) ends.push({ x: lastPt[0], y: lastPt[1], v: lastPt[2], color });
      if (this.series.length >= 2) { const it = el('span'); it.append(el('span', { class: 'key', style: `background:${color}` }), document.createTextNode(s.name)); this.legendEl.append(it); }
    });
    ends.sort((a, b) => a.y - b.y); let prevY = -99;
    ends.forEach(e => { if (Math.abs(e.y - prevY) < 12) return; const t = mk('text', { x: e.x + 6, y: e.y + 4, class: 'end-label' }); t.textContent = this.opts.yFmt(e.v); svg.append(t); prevY = e.y; });
    this.cross = mk('line', { x1: 0, x2: 0, y1: m.t, y2: m.t + ph, class: 'crosshair' }); svg.append(this.cross);
    this.markers = this.series.map((s, si) => { const c = mk('circle', { r: 4.5, class: 'marker', fill: s.color || seriesColor(si) }); svg.append(c); return c; });
    const hit = mk('rect', { x: m.l, y: m.t, width: pw, height: ph, class: 'hit' }); svg.append(hit);
    const move = ev => { const rect = svg.getBoundingClientRect(); const px = (ev.clientX - rect.left) * (W / rect.width); const i = Math.max(0, Math.min(n - 1, Math.round((px - m.l) / (pw || 1) * (n - 1)))); this.showHover(dates[i], true); };
    hit.addEventListener('pointermove', move); hit.addEventListener('pointerdown', move);
    hit.addEventListener('pointerleave', () => { this.hideHover(); this.linked.forEach(c => c.hideHover()); });
    if (this.hoverDate) this.showHover(this.hoverDate, false);
  }
  showHover(date, propagate) {
    const i = this.dates ? this.dates.indexOf(date) : -1;
    if (i < 0) { this.hideHover(); if (propagate) this.linked.forEach(c => c.showHover(date, false)); return; }
    this.hoverDate = date; const x = this.xs(i); this.cross.setAttribute('x1', x); this.cross.setAttribute('x2', x); this.cross.style.opacity = 1;
    this.tip.textContent = ''; this.tip.append(el('div', { class: 'tt-date', text: date }));
    this.series.forEach((s, si) => {
      const v = this.maps[si].get(date); const c = this.markers[si];
      if (isNum(v)) { c.setAttribute('cx', x); c.setAttribute('cy', this.ys(v)); c.style.opacity = 1; } else c.style.opacity = 0;
      const row = el('div', { class: 'tt-row' }); row.append(el('span', { class: 'tt-key', style: `background:${s.color || seriesColor(si)}` }), el('span', { class: 'tt-val', text: isNum(v) ? (s.fmt || this.opts.yFmt)(v) : '—' }), el('span', { class: 'tt-name', text: s.name }));
      this.tip.append(row);
    });
    this.tip.style.display = 'block';
    const rect = this.svg.getBoundingClientRect(); const scale = rect.width / this.W; const left = x * scale; const tw = this.tip.offsetWidth || 140;
    this.tip.style.left = (left + 12 + tw > rect.width ? left - tw - 12 : left + 12) + 'px'; this.tip.style.top = (this.legendEl.offsetHeight + 8) + 'px';
    if (propagate) this.linked.forEach(c => c.showHover(date, false));
  }
  hideHover() { this.hoverDate = null; if (this.cross) this.cross.style.opacity = 0; (this.markers || []).forEach(c => c.style.opacity = 0); this.tip.style.display = 'none'; }
}
function link(...charts) { charts.forEach(c => { c.linked = charts.filter(o => o !== c); }); }
function rangeControl(charts, initial = '1Y', keys = ['1M', '3M', '6M', '1Y', '2Y']) {
  const seg = el('div', { class: 'seg', role: 'group', 'aria-label': '時間範圍' });
  keys.forEach(k => { const b = el('button', { type: 'button', 'aria-pressed': k === initial ? 'true' : 'false', text: k }); b.onclick = () => { $$('button', seg).forEach(x => x.setAttribute('aria-pressed', 'false')); b.setAttribute('aria-pressed', 'true'); charts.forEach(c => c.setRange(k)); }; seg.append(b); });
  return seg;
}
function dataTable(container, series, limit = 30) {
  series = series.filter(Boolean); if (!series.length) return;
  const det = el('details', { class: 'tbl' }); det.append(el('summary', { text: '顯示數據表（最近 ' + limit + ' 筆）' }));
  const dates = Array.from(new Set(series.flatMap(s => s.dates))).sort().slice(-limit).reverse();
  const tbl = el('table', { class: 'data' }); const thead = el('tr'); thead.append(el('th', { text: '日期' })); series.forEach(s => thead.append(el('th', { text: s.name })));
  tbl.append(el('thead', {}, thead)); const tb = el('tbody');
  const maps = series.map(s => { const mp = new Map(); s.dates.forEach((d, i) => mp.set(d, s.values[i])); return mp; });
  dates.forEach(d => { const tr = el('tr'); tr.append(el('td', { text: d })); maps.forEach((mp, i) => tr.append(el('td', { text: isNum(mp.get(d)) ? (series[i].fmt || (v => fmt(v, 2)))(mp.get(d)) : '—' }))); tb.append(tr); });
  tbl.append(tb); det.append(el('div', { class: 'table-wrap' }, tbl)); container.append(det);
}

/* ------------------------------------------------------------ Markdown（受控子集：先跳脫 HTML 再轉換） */
function mdToHtml(md) {
  const lines = (md || '').replace(/\r/g, '').split('\n'); const out = []; let i = 0;
  const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>').replace(/\\\*/g, '*');
  while (i < lines.length) {
    const l = lines[i];
    if (/^\s*$/.test(l)) { i++; continue; }
    const mh = l.match(/^(#{1,4})\s+(.*)$/); if (mh) { out.push(`<h${mh[1].length}>${inline(mh[2])}</h${mh[1].length}>`); i++; continue; }
    if (l.startsWith('>')) { const b = []; while (i < lines.length && lines[i].startsWith('>')) { b.push(lines[i].replace(/^>\s?/, '')); i++; } out.push(`<blockquote>${inline(b.join(' '))}</blockquote>`); continue; }
    if (l.trim().startsWith('|')) {
      const rows = []; while (i < lines.length && lines[i].trim().startsWith('|')) { rows.push(lines[i].trim()); i++; }
      const cells = r => r.replace(/^\||\|$/g, '').split('|').map(c => c.trim());
      const body = rows.filter(r => !/^\|?\s*:?-{2,}/.test(r)); if (!body.length) continue;
      let h = '<div class="table-wrap"><table><thead><tr>' + cells(body[0]).map(c => `<th>${inline(c)}</th>`).join('') + '</tr></thead><tbody>';
      body.slice(1).forEach(r => { h += '<tr>' + cells(r).map(c => `<td>${inline(c)}</td>`).join('') + '</tr>'; });
      out.push(h + '</tbody></table></div>'); continue;
    }
    if (/^\s*[-*]\s+/.test(l) || /^\s*\d+\.\s+/.test(l)) {
      const ordered = /^\s*\d+\./.test(l); const items = [];
      while (i < lines.length && (/^\s*[-*]\s+/.test(lines[i]) || /^\s*\d+\.\s+/.test(lines[i]))) { items.push(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, '')); i++; }
      out.push(`<${ordered ? 'ol' : 'ul'}>` + items.map(x => `<li>${inline(x)}</li>`).join('') + `</${ordered ? 'ol' : 'ul'}>`); continue;
    }
    const p = []; while (i < lines.length && !/^\s*$/.test(lines[i]) && !/^(#|>|\||\s*[-*]\s|\s*\d+\.\s)/.test(lines[i])) { p.push(lines[i]); i++; }
    if (p.length) out.push(`<p>${inline(p.join(' '))}</p>`); else i++;
  }
  return out.join('\n');
}

/* ------------------------------------------------------------ 載入資料 */
async function loadAll() {
  const D = window.FH_DATA;
  if (D) {  // 單一 HTML 模式：資料已內嵌（pipeline/build_single.py）
    Object.assign(S, { latest: D.latest, breadth: D.breadth, macro: D.macro, valuation: D.valuation, registry: D.registry, reportMd: D.report_md, insightMd: D.insight_md, status: D.status, live: false, builtAt: D.built_at });
    S.universe = (D.universe_quotes && D.universe_quotes.tickers) || {};
    S.indexHist = parseCsv(D.index_pe_csv); S.tickerHist = new Map();
    [D.pe_csv_prev, D.pe_csv].forEach(c => parseCsv(c).forEach(r => { if (!S.tickerHist.has(r.symbol)) S.tickerHist.set(r.symbol, []); S.tickerHist.get(r.symbol).push(r); }));
    S.indexes = (S.registry && S.registry.indexes) || []; S.aliases = (S.registry && S.registry.aliases) || {}; S.byKey = Object.fromEntries(S.indexes.map(x => [x.key, x]));
    return;
  }
  const bust = '?v=' + Math.floor(Date.now() / 600000);
  const j = p => fetch(p + bust).then(r => r.ok ? r.json() : null).catch(() => null);
  const t = p => fetch(p + bust).then(r => r.ok ? r.text() : null).catch(() => null);
  const year = new Date().getUTCFullYear();
  const [latest, breadth, macro, valuation, registry, reportMd, insightMd, idxCsv, peCsv, peCsvPrev, status, ping] = await Promise.all([
    j('data/latest.json'), j('data/breadth.json'), j('data/macro.json'), j('data/valuation.json'), j('data/registry.json'),
    t('reports/latest.md'), t('reports/latest-insight.md'), t('data/history/index_pe.csv'), t(`data/history/pe/${year}.csv`), t(`data/history/pe/${year - 1}.csv`), j('data/status.json'),
    fetch('/api/ping', { signal: AbortSignal.timeout(1500) }).then(r => r.ok ? r.json() : null).catch(() => null),
  ]);
  Object.assign(S, { latest, breadth, macro, valuation, registry, reportMd, insightMd, status, live: !!(ping && ping.live) });
  S.indexHist = parseCsv(idxCsv);
  S.tickerHist = new Map();
  [peCsvPrev, peCsv].forEach(c => parseCsv(c).forEach(r => { if (!S.tickerHist.has(r.symbol)) S.tickerHist.set(r.symbol, []); S.tickerHist.get(r.symbol).push(r); }));
  S.indexes = (registry && registry.indexes) || []; S.aliases = (registry && registry.aliases) || {};
  S.byKey = Object.fromEntries(S.indexes.map(x => [x.key, x]));
}
async function loadUniverse() {
  if (S.universe) return S.universe;
  if (!S.universeLoading) S.universeLoading = fetch('data/universe_quotes.json').then(r => r.ok ? r.json() : null).catch(() => null).then(u => { S.universe = u && u.tickers ? u.tickers : {}; return S.universe; });
  return S.universeLoading;
}

/* ------------------------------------------------------------ 各區塊 */
function renderHeader() {
  const asof = (S.latest && S.latest.asof) || (S.breadth && S.breadth.asof) || '—';
  $('#asof').textContent = `資料日期 ${asof}` + (S.builtAt ? `（打包 ${S.builtAt}）` : '');
  $('#liveBadge').style.display = S.live ? '' : 'none';
}
function renderOverview() {
  const box = $('#overview'); box.textContent = '';
  const L = S.latest; if (!L) { box.append(el('div', { class: 'empty', text: '尚未產生資料：請先執行 python3 pipeline/run_all.py' })); return; }
  const rows = Object.fromEntries((L.indexes || []).map(r => [r.key, r]));
  ['SPX', 'NDX', 'DJI', 'RUT', 'SOX', 'TSX'].forEach(k => { const r = rows[k]; if (!r) return; box.append(tile(r.name, fmt(r.close, r.close > 1000 ? 0 : 2), signed(r.d1, 2, '%') + '  今日', `5 日 ${signed(r.d5, 1, '%')} · 距 52 週高 ${signed(r.from_high, 1, '%')}`, { deltaClass: dir(r.d1) })); });
  const M = L.macro || {};
  if (M.DFII10) box.append(tile('10 年期實質利率', fmt(M.DFII10.v, 2) + '%', signed(M.DFII10.d5, 0, ' bp') + '  5 日', `一年百分位 ${fmt(M.DFII10.rank1y, 0)}`));
  if (M.GOLD) box.append(tile('黃金 (USD/oz)', fmt(M.GOLD.v, 0), signed(M.GOLD.d5, 1, '%') + '  5 日', `一年百分位 ${fmt(M.GOLD.rank1y, 0)}`, { deltaClass: dir(M.GOLD.d5) }));
  if (M.VIX) box.append(tile('VIX', fmt(M.VIX.v, 1), signed(M.VIX.d1, 1, '%') + '  今日', `一年百分位 ${fmt(M.VIX.rank1y, 0)}`));
  if (M.MOVE) box.append(tile('MOVE', fmt(M.MOVE.v, 0), signed(M.MOVE.d1, 1, '%') + '  今日', `一年百分位 ${fmt(M.MOVE.rank1y, 0)}`));
}
function renderReport() {
  const L = S.latest; const sum = $('#summary'); const sg = $('#signals'); sg.textContent = '';
  if (!L) { sum.textContent = '尚無日報。'; return; }
  sum.textContent = L.summary || '';
  const lvlName = { alert: '警示', watch: '留意', good: '正向', info: '資訊' };
  const topicName = { breadth: '參與度', rates: '利率', gold: '黃金', vol: '波動率', valuation: '估值', index: '指數' };
  (L.signals || []).forEach(s => { const c = el('div', { class: 'signal ' + s.level }); c.append(el('div', { class: 'lvl', text: `${lvlName[s.level] || s.level} · ${topicName[s.topic] || s.topic}` }), el('div', { class: 'short', text: s.short }), el('div', { class: 'text', text: s.text })); sg.append(c); });
  const ins = $('#insight'); ins.textContent = '';
  if (S.insightMd) { ins.append(el('h2', { text: 'AI 解讀' })); const d = el('div', { class: 'md card' }); d.innerHTML = mdToHtml(S.insightMd); ins.append(d); }
  const rep = $('#reportMd'); rep.innerHTML = S.reportMd ? mdToHtml(S.reportMd) : '<p class="empty">尚無日報</p>';
}
function mccOf(r) { const m = r && r.mcc; if (!m) return null; return m.v || m.i || null; }
function renderBreadth() {
  const B = S.breadth; const host = $('#breadthTable'); host.textContent = '';
  if (!B) { host.append(el('div', { class: 'empty', text: '尚無參與度資料' })); return; }
  const wins = B.windows || [10, 20, 50, 100, 150, 200, 250];
  const tbl = el('table', { class: 'data' }); const hr = el('tr');
  ['指數', '收盤', '今日', '成分股', ...wins.map(w => w + 'D'), '20D 5 日變化', '52 週淨新高', 'McClellan 累積', '震盪'].forEach(h => hr.append(el('th', { text: h })));
  tbl.append(el('thead', {}, hr)); const tb = el('tbody');
  (B.order || Object.keys(B.indexes)).forEach(k => {
    const r = B.indexes[k]; if (!r) return; const tr = el('tr', { class: 'clickable' });
    const nameTd = el('td', { class: 'name', text: r.name || k }); if (r.approx) nameTd.append(el('span', { class: 'approx', text: '近似' })); tr.append(nameTd);
    tr.append(el('td', { text: fmt(r.close, r.close > 1000 ? 0 : 2) }));
    tr.append(el('td', { text: signed(r.chg_pct, 2, '%'), class: dir(r.chg_pct) === 'up' ? 'pos' : dir(r.chg_pct) === 'down' ? 'neg' : '' }));
    tr.append(el('td', { text: `${r.priced ?? '—'}` }));
    wins.forEach(w => { const v = (r.latest || {})[String(w)]; const td = el('td', { text: isNum(v) ? fmt(v, 0) : '—' }); td.setAttribute('style', heat(v)); tr.append(td); });
    const l20 = (r.latest || {})['20'], w20 = (r.week || {})['20']; const d = (isNum(l20) && isNum(w20)) ? l20 - w20 : null;
    tr.append(el('td', { text: signed(d, 0, ' pt'), class: dir(d) === 'up' ? 'pos' : dir(d) === 'down' ? 'neg' : '' }));
    const nh = (r.nhnl || {}).latest; const tdN = el('td', { text: isNum(nh) ? signed(nh, 1, '%') : '—' }); tdN.setAttribute('style', heat(nh, 0, 8)); tr.append(tdN);
    const m = mccOf(r); tr.append(el('td', { text: m && isNum(m.latest_sum) ? fmt(m.latest_sum, 0) : '—' }));
    const o = m ? m.latest_osc : null; tr.append(el('td', { text: isNum(o) ? signed(o, 0) : '—', class: dir(o) === 'up' ? 'pos' : dir(o) === 'down' ? 'neg' : '' }));
    tr.onclick = () => { $('#breadthIndex').value = k; drawBreadthChart(); }; tb.append(tr);
  });
  tbl.append(tb); host.append(tbl);
  const sel = $('#breadthIndex'); sel.textContent = '';
  (B.order || Object.keys(B.indexes)).forEach(k => sel.append(el('option', { value: k, text: (B.indexes[k].name || k) + (B.indexes[k].approx ? '（近似）' : '') })));
  sel.value = B.indexes.SPX ? 'SPX' : sel.options[0].value; sel.onchange = drawBreadthChart;
  S.breadthChart = S.breadthChart || new LineChart($('#breadthChart'), { height: 280, yMin: 0, yMax: 100, yFmt: v => fmt(v, 0) + '%', bands: [{ y: 30, label: '超賣 30' }, { y: 70, label: '超買 70' }], range: '1Y' });
  S.nhnlChart = S.nhnlChart || new LineChart($('#nhnlChart'), { height: 220, yFmt: v => signed(v, 1, '%'), bands: [{ y: 5, label: '+5 極端貪婪' }, { y: -5, label: '−5 極端恐懼' }], range: '1Y', area: true });
  S.mccSumChart = S.mccSumChart || new LineChart($('#mccSumChart'), { height: 200, yFmt: v => fmt(v, 0), range: '1Y', area: true });
  S.mccOscChart = S.mccOscChart || new LineChart($('#mccOscChart'), { height: 150, yFmt: v => signed(v, 0), bands: [{ y: 0, label: '0' }], range: '1Y', area: true });
  link(S.mccSumChart, S.mccOscChart);
  const ctl = $('#breadthRange'); ctl.textContent = ''; ctl.append(rangeControl([S.breadthChart, S.nhnlChart, S.mccSumChart, S.mccOscChart], '1Y', ['3M', '6M', '1Y']));
  drawBreadthChart();
}
function drawBreadthChart() {
  const k = $('#breadthIndex').value; const r = S.breadth.indexes[k]; if (!r) return;
  const h = r.history || {}; const name = r.name || k;
  const series = ['20', '50', '200'].filter(w => h[w]).map((w, i) => ({ name: `站上 ${w} 日線 %`, dates: h.dates, values: h[w], color: seriesColor(i), fmt: v => fmt(v, 0) + '%' }));
  $('#breadthChartTitle').textContent = `${name} 參與度歷史`; S.breadthChart.setSeries(series);
  const tb = $('#breadthChartTable'); tb.textContent = ''; dataTable(tb, series, 30);
  const nh = r.nhnl || {}; const nhS = nh.history ? [{ name: '52 週淨新高 %', dates: h.dates, values: nh.history, color: seriesColor(0), fmt: v => signed(v, 1, '%') }] : [];
  $('#nhnlTitle').textContent = `${name} 52 週淨新高` + (isNum(nh.nh) ? `（新高 ${nh.nh} 檔 / 新低 ${nh.nl} 檔）` : ''); S.nhnlChart.setSeries(nhS);
  const t2 = $('#nhnlTable'); t2.textContent = ''; dataTable(t2, nhS, 30);
  const m = mccOf(r);
  const sumS = m ? [{ name: 'McClellan 累積指數', dates: h.dates, values: m.sum, color: seriesColor(0), fmt: v => fmt(v, 0) }] : [];
  const oscS = m ? [{ name: 'McClellan 震盪指標', dates: h.dates, values: m.osc, color: seriesColor(1), fmt: v => signed(v, 0) }] : [];
  $('#mccTitle').textContent = `${name} McClellan 成交量累積指數` + (m && isNum(m.rank1y) ? `（一年百分位 ${fmt(m.rank1y, 0)}）` : '');
  S.mccSumChart.setSeries(sumS); S.mccOscChart.setSeries(oscS);
  const t3 = $('#mccTable'); t3.textContent = ''; dataTable(t3, [...sumS, ...oscS], 30);
}
function initInfo() {
  $$('.info').forEach(b => { b.addEventListener('click', e => { e.stopPropagation(); const w = b.parentElement; const open = w.classList.contains('open'); $$('.info-wrap.open').forEach(x => x.classList.remove('open')); if (!open) w.classList.add('open'); }); });
  document.addEventListener('click', () => $$('.info-wrap.open').forEach(x => x.classList.remove('open')));
}
function seriesOf(key, name, fmtFn) { const s = ((S.macro && S.macro.series) || {})[key]; return s ? { name: name || s.name, dates: s.dates, values: s.values, fmt: fmtFn } : null; }
function renderRates() {
  const M = (S.latest && S.latest.macro) || {}; const tiles = $('#ratesTiles'); tiles.textContent = '';
  if (M.DFII10) tiles.append(tile('10 年期實質利率 (TIPS)', fmt(M.DFII10.v, 2) + '%', `5 日 ${signed(M.DFII10.d5, 0, ' bp')} · 21 日 ${signed(M.DFII10.d21, 0, ' bp')}`, `一年區間 ${fmt(M.DFII10.lo1y, 2)}–${fmt(M.DFII10.hi1y, 2)}% · 百分位 ${fmt(M.DFII10.rank1y, 0)}`));
  if (M.GOLD) tiles.append(tile('黃金 (USD/oz)', fmt(M.GOLD.v, 0), `5 日 ${signed(M.GOLD.d5, 1, '%')} · 21 日 ${signed(M.GOLD.d21, 1, '%')}`, `一年區間 ${fmt(M.GOLD.lo1y, 0)}–${fmt(M.GOLD.hi1y, 0)} · 百分位 ${fmt(M.GOLD.rank1y, 0)}`, { deltaClass: dir(M.GOLD.d5) }));
  if (M.DGS10) tiles.append(tile('10 年期公債殖利率', fmt(M.DGS10.v, 2) + '%', `5 日 ${signed(M.DGS10.d5, 0, ' bp')}`, `通膨預期 ${M.T10YIE ? fmt(M.T10YIE.v, 2) + '%' : '—'}（5 日 ${M.T10YIE ? signed(M.T10YIE.d5, 0, ' bp') : '—'}）`));
  if (isNum(M.corr_gold_real_60d)) tiles.append(tile('黃金 vs 實質利率 60 日相關', signed(M.corr_gold_real_60d, 2), M.corr_gold_real_60d < -0.2 ? '負相關成立' : '負相關鬆動', '日變動的 Pearson 相關係數'));
  if (M.DXY) tiles.append(tile('美元指數', fmt(M.DXY.v, 2), `5 日 ${signed(M.DXY.d5, 1, '%')}`, `一年百分位 ${fmt(M.DXY.rank1y, 0)}`));
  S.rateChart = S.rateChart || new LineChart($('#rateChart'), { height: 220, yFmt: v => fmt(v, 2) + '%', range: '6M' });
  S.goldChart = S.goldChart || new LineChart($('#goldChart'), { height: 220, yFmt: v => fmt(v, 0), range: '6M', area: true });
  link(S.rateChart, S.goldChart);
  const real = seriesOf('DFII10', '10 年期實質利率 %', v => fmt(v, 2) + '%');
  const nom = seriesOf('TNX', '10 年期名目殖利率 %', v => fmt(v, 2) + '%');
  if (real) { real.color = seriesColor(0); S.rateChart.setSeries([real]); $('#rateChartTitle').textContent = '10 年期實質利率（TIPS，%）'; }
  else if (nom) { nom.color = seriesColor(0); S.rateChart.setSeries([nom]); $('#rateChartTitle').textContent = '10 年期名目殖利率（實質利率暫無資料）'; }
  const gold = seriesOf('GOLD', '黃金 USD/oz', v => fmt(v, 0)); if (gold) { gold.color = seriesColor(1); S.goldChart.setSeries([gold]); }
  const ctl = $('#ratesRange'); ctl.textContent = ''; ctl.append(rangeControl([S.rateChart, S.goldChart], '6M'));
  const tb = $('#ratesTable'); tb.textContent = ''; dataTable(tb, [real || nom, gold, seriesOf('DGS10', '10 年期名目 %', v => fmt(v, 2) + '%'), seriesOf('T10YIE', '通膨預期 %', v => fmt(v, 2) + '%')], 30);
}
function renderVol() {
  const M = (S.latest && S.latest.macro) || {}; const tiles = $('#volTiles'); tiles.textContent = '';
  const zoneV = v => v >= 30 ? '恐慌' : v >= 22 ? '偏高' : v >= 15 ? '正常' : '低檔';
  if (M.VIX) tiles.append(tile('VIX（美股波動率）', fmt(M.VIX.v, 1), `今日 ${signed(M.VIX.d1, 1, '%')} · 5 日 ${signed(M.VIX.d5, 1, '%')}`, `${zoneV(M.VIX.v)} · 一年區間 ${fmt(M.VIX.lo1y, 1)}–${fmt(M.VIX.hi1y, 1)} · 百分位 ${fmt(M.VIX.rank1y, 0)}`));
  if (M.MOVE) tiles.append(tile('MOVE（美債波動率）', fmt(M.MOVE.v, 0), `今日 ${signed(M.MOVE.d1, 1, '%')} · 5 日 ${signed(M.MOVE.d5, 1, '%')}`, `${M.MOVE.v >= 120 ? '壓力區' : M.MOVE.v >= 100 ? '偏高' : '溫和'} · 一年區間 ${fmt(M.MOVE.lo1y, 0)}–${fmt(M.MOVE.hi1y, 0)} · 百分位 ${fmt(M.MOVE.rank1y, 0)}`));
  S.vixChart = S.vixChart || new LineChart($('#vixChart'), { height: 220, yFmt: v => fmt(v, 0), range: '1Y', area: true });
  S.moveChart = S.moveChart || new LineChart($('#moveChart'), { height: 220, yFmt: v => fmt(v, 0), range: '1Y', area: true });
  link(S.vixChart, S.moveChart);
  const vix = seriesOf('VIX', 'VIX', v => fmt(v, 1)); if (vix) { vix.color = seriesColor(0); S.vixChart.setSeries([vix]); }
  const mv = seriesOf('MOVE', 'MOVE', v => fmt(v, 1)); if (mv) { mv.color = seriesColor(1); S.moveChart.setSeries([mv]); }
  const ctl = $('#volRange'); ctl.textContent = ''; ctl.append(rangeControl([S.vixChart, S.moveChart], '1Y'));
  const tb = $('#volTable'); tb.textContent = ''; dataTable(tb, [vix, mv], 30);
}

/* ------------------------------------------------------------ Forward PE 查詢 */
function indexPeTable() {
  const host = $('#indexPeTable'); host.textContent = ''; const V = S.valuation; if (!V || !V.indexes) return;
  const tbl = el('table', { class: 'data' }); const hr = el('tr');
  ['指數', '收盤', 'Forward PE（下一財年）', 'NTM PE（混合 12 月）', 'Trailing PE', '成分股中位數', '市值覆蓋', '成分股', '歷史'].forEach(h => hr.append(el('th', { text: h })));
  tbl.append(el('thead', {}, hr)); const tb = el('tbody');
  const hist = (S.latest && S.latest.pe) || {};
  Object.entries(V.indexes).forEach(([k, a]) => {
    const tr = el('tr', { class: 'clickable' }); const nm = el('td', { class: 'name', text: a.name }); if (a.approx) nm.append(el('span', { class: 'approx', text: '近似' })); tr.append(nm);
    const h = (hist[k] && hist[k].hist) || {};
    [fmt(a.close, a.close > 1000 ? 0 : 2), peFmt(a.fpe), peFmt(a.ntm), peFmt(a.tpe), peFmt(a.median_fpe), isNum(a.fpe_cov) ? fmt(a.fpe_cov * 100, 0) + '%' : '—', `${a.fpe_n ?? '—'}/${a.members ?? '—'}`, isNum(h.rank) ? `第 ${fmt(h.rank, 0)} 百分位（${h.n} 日）` : `累積中（${h.n || 0} 日）`].forEach(x => tr.append(el('td', { text: x })));
    tr.onclick = () => showTarget({ kind: 'index', key: k }); tb.append(tr);
  });
  tbl.append(tb); host.append(tbl);
}
function normSym(q) { const s = q.trim().toUpperCase(); if (s.startsWith('^') || s.includes('=')) return s; if (/^[A-Z0-9]+\.[A-Z]{1,2}$/.test(s) && !/\.(TO|V|TW|HK|L|SS|SZ|T|PA|DE|AS)$/.test(s)) return s.replace('.', '-'); return s; }
function resolveQuery(q) {
  const raw = q.trim(); const up = raw.toUpperCase(); if (!raw) return null;
  const a = S.aliases[up]; if (a) return S.byKey[a] ? { kind: 'index', key: a } : { kind: 'symbol', symbol: a };
  const ix = S.indexes.find(x => up === x.name.toUpperCase() || up === x.en.toUpperCase() || up === x.yahoo.toUpperCase()); if (ix) return { kind: 'index', key: ix.key };
  const sym = normSym(raw);
  if (S.valuation && S.valuation.tickers[sym]) return { kind: 'symbol', symbol: sym };
  if (S.universe && S.universe[sym]) return { kind: 'symbol', symbol: sym };
  const byName = findByName(raw); if (byName) return byName;
  return { kind: 'symbol', symbol: sym, unverified: true };
}
function findByName(q) {
  const ql = q.toLowerCase(); let best = null;
  const T = (S.valuation && S.valuation.tickers) || {};
  for (const [s, r] of Object.entries(T)) { if ((r.n || '').toLowerCase().startsWith(ql)) { if (!best || (r.mc || 0) > best.mc) best = { sym: s, mc: r.mc || 0 }; } }
  if (!best && S.universe) for (const [s, r] of Object.entries(S.universe)) { if ((r[0] || '').toLowerCase().startsWith(ql)) { if (!best || (r[4] || 0) > best.mc) best = { sym: s, mc: r[4] || 0 }; } }
  return best ? { kind: 'symbol', symbol: best.sym } : null;
}
function suggestions(q) {
  const up = q.trim().toUpperCase(); const ql = q.trim().toLowerCase(); if (!up) return [];
  const out = []; const seen = new Set();
  const push = (kind, id, name, extra) => { const k = kind + ':' + id; if (seen.has(k) || out.length >= 9) return; seen.add(k); out.push({ kind, id, name, extra }); };
  S.indexes.forEach(x => { if (x.key.startsWith(up) || x.name.includes(q.trim()) || x.en.toUpperCase().includes(up) || x.yahoo.toUpperCase() === up) push('index', x.key, x.name + ' · ' + x.en, x.yahoo); });
  Object.entries(S.aliases).forEach(([al, target]) => { if (!al.startsWith(up)) return; if (S.byKey[target]) push('index', target, S.byKey[target].name + ' · ' + S.byKey[target].en, S.byKey[target].yahoo); else push('symbol', target, al, ''); });
  const T = (S.valuation && S.valuation.tickers) || {};
  Object.entries(T).forEach(([s, r]) => { if (s.startsWith(up)) push('symbol', s, r.n || '', r.x || ''); });
  if (S.universe) Object.entries(S.universe).forEach(([s, r]) => { if (s.startsWith(up)) push('symbol', s, r[0] || '', r[1] || ''); });
  if (ql.length >= 2) {
    Object.entries(T).forEach(([s, r]) => { if ((r.n || '').toLowerCase().includes(ql)) push('symbol', s, r.n || '', r.x || ''); });
    if (S.universe) Object.entries(S.universe).forEach(([s, r]) => { if ((r[0] || '').toLowerCase().includes(ql)) push('symbol', s, r[0] || '', r[1] || ''); });
  }
  return out.slice(0, 9);
}
function initSearch() {
  const inp = $('#peQuery'); const box = $('#peSuggest'); let active = -1; let items = [];
  const draw = () => { box.textContent = ''; items.forEach((it, i) => { const d = el('div', { class: i === active ? 'active' : '' }); d.append(el('span', { class: 'sym', text: it.id }), el('span', { class: 'nm', text: it.name }), el('span', { class: 'kind', text: it.kind === 'index' ? '指數' : it.extra || '' })); d.onmousedown = e => { e.preventDefault(); pick(it); }; box.append(d); }); box.style.display = items.length ? 'block' : 'none'; };
  const pick = it => { inp.value = it.id; box.style.display = 'none'; showTarget(it.kind === 'index' ? { kind: 'index', key: it.id } : { kind: 'symbol', symbol: it.id }); };
  inp.addEventListener('input', () => { items = suggestions(inp.value); active = -1; draw(); loadUniverse().then(() => { if (document.activeElement === inp) { items = suggestions(inp.value); draw(); } }); });
  inp.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { active = Math.min(items.length - 1, active + 1); draw(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { active = Math.max(-1, active - 1); draw(); e.preventDefault(); }
    else if (e.key === 'Enter') { e.preventDefault(); box.style.display = 'none'; if (active >= 0) pick(items[active]); else submit(); }
    else if (e.key === 'Escape') box.style.display = 'none';
  });
  inp.addEventListener('blur', () => setTimeout(() => { box.style.display = 'none'; }, 150));
  const submit = async () => { await loadUniverse(); const r = resolveQuery(inp.value); if (r) showTarget(r); };
  $('#peGo').onclick = submit;
  $$('#peChips .chip').forEach(c => { c.onclick = () => { inp.value = c.dataset.q; submit(); }; });
}
async function showTarget(t) {
  const host = $('#peResult'); host.classList.add('loading');
  try {
    if (t.kind === 'index') await renderIndexResult(t.key); else await renderSymbolResult(t.symbol);
    try { history.replaceState(null, '', '#pe?q=' + encodeURIComponent(t.kind === 'index' ? t.key : t.symbol)); } catch (e) { }
  } finally { host.classList.remove('loading'); }
}
async function apiLookup(q, live) {
  if (!S.live) return null;
  try { const r = await fetch('/api/lookup?q=' + encodeURIComponent(q) + (live ? '&live=1' : ''), { signal: AbortSignal.timeout(30000) }); return r.ok ? r.json() : null; } catch (e) { return null; }
}
function peHistorySeries(rows) {
  const rs = (rows || []).filter(r => r.date).sort((a, b) => a.date < b.date ? -1 : 1);
  const dates = rs.map(r => r.date);
  return [{ name: 'Forward PE（下一財年）', dates, values: rs.map(r => num(r.fpe)), color: seriesColor(0), fmt: v => fmt(v, 1) }, { name: 'NTM PE', dates, values: rs.map(r => num(r.ntm)), color: seriesColor(1), fmt: v => fmt(v, 1) }].filter(s => s.values.some(isNum));
}
function chartCard(host, title, sub, opts, series) {
  const cw = el('div', { class: 'chart-card', style: 'margin-top:12px' }); cw.append(el('div', { class: 'chart-title' }, el('b', { text: title }), sub ? el('span', { text: sub }) : null)); const cc = el('div'); cw.append(cc); host.append(cw);
  new LineChart(cc, opts).setSeries(series);
}
async function renderIndexResult(key) {
  const V = S.valuation; let a = V && V.indexes && V.indexes[key]; let live = null;
  if (!a && S.live) { live = await apiLookup(key, true); a = live && live.aggregate; }
  const ix = S.byKey[key] || {}; const host = $('#peResult'); host.textContent = '';
  if (!a) { host.append(el('div', { class: 'empty', text: `${ix.name || key} 尚未有估值資料。全量模式（python3 pipeline/run_all.py）會計算此指數；本機 serve.py 模式可即時計算。` })); return; }
  const head = el('div', { class: 'result-head' }); head.append(el('span', { class: 'sym', text: ix.name || a.name || key }), el('span', { class: 'nm', text: `${ix.en || ''} · ${ix.yahoo || ''}` }));
  if (ix.approx) head.append(el('span', { class: 'badge warn', text: '成分股近似' })); if (live) head.append(el('span', { class: 'badge live', text: '即時計算' }));
  head.append(el('span', { class: 'px', text: fmt(a.close, a.close > 1000 ? 0 : 2) })); host.append(head);
  const tiles = el('div', { class: 'grid kpi', style: 'margin:12px 0' });
  tiles.append(tile('Forward PE（下一財年）', peFmt(a.fpe), `覆蓋 ${a.fpe_n}/${a.members} 檔 · 市值 ${fmt((a.fpe_cov || 0) * 100, 0)}%`, null, { hero: true }));
  tiles.append(tile('NTM PE（混合 12 個月）', peFmt(a.ntm), `覆蓋 ${a.ntm_n}/${a.members} 檔`, '最接近 Bloomberg BEst P/E'));
  tiles.append(tile('Trailing PE', peFmt(a.tpe), '過去 12 個月盈餘'));
  tiles.append(tile('本財年 PE', peFmt(a.cpe), '本財年 EPS 共識'));
  tiles.append(tile('成分股 Fwd PE 中位數', peFmt(a.median_fpe), `NTM 中位數 ${peFmt(a.median_ntm)}`));
  tiles.append(tile('虧損公司比例', isNum(a.neg_share) ? fmt(a.neg_share, 0) + '%' : '—', '下一財年 EPS ≤ 0'));
  host.append(tiles);
  const hist = (S.latest && S.latest.pe && S.latest.pe[key] && S.latest.pe[key].hist) || {};
  const rows = (live && live.history) || S.indexHist.filter(r => r.index === key);
  host.append(el('p', { class: 'hint', text: isNum(hist.rank) ? `Forward PE 位於自 ${hist.since} 累積以來第 ${fmt(hist.rank, 0)} 百分位；區間 ${fmt(hist.min, 1)}（${hist.min_date}）– ${fmt(hist.max, 1)}（${hist.max_date}）。` : `PE 歷史自 ${rows[0] ? rows[0].date : (V && V.asof) || '今日'} 起每日累積（目前 ${rows.length} 日），累積 20 日後顯示百分位。` }));
  chartCard(host, `${ix.name || key} PE 歷史`, '每日快照累積', { height: 240, yFmt: v => fmt(v, 1), range: '2Y' }, peHistorySeries(rows));
  if (live && live.chart) chartCard(host, '指數走勢（1 年）', ix.yahoo, { height: 200, yFmt: v => fmt(v, 0), range: '1Y', area: true }, [{ name: ix.name || key, dates: live.chart.dates, values: live.chart.close, color: seriesColor(0), fmt: v => fmt(v, 0) }]);
  const tt = el('div', { class: 'card', style: 'margin-top:12px' }); tt.append(el('h3', { text: '權重最大的成分股', style: 'margin-top:0' }));
  const tbl = el('table', { class: 'data' }); const hr = el('tr'); ['代號', '名稱', '權重', '今日', 'Fwd PE', 'NTM PE', 'Trailing PE'].forEach(h => hr.append(el('th', { text: h }))); tbl.append(el('thead', {}, hr)); const tb = el('tbody');
  (a.top || []).forEach(t => { const tr = el('tr', { class: 'clickable' }); tr.append(el('td', { text: t.s }), el('td', { class: 'name', text: (t.n || '').slice(0, 36) }), el('td', { text: fmt(t.w, 1) + '%' }), el('td', { text: signed(t.c, 2, '%'), class: dir(t.c) === 'up' ? 'pos' : dir(t.c) === 'down' ? 'neg' : '' }), el('td', { text: peFmt(t.fpe) }), el('td', { text: peFmt(t.ntm) }), el('td', { text: peFmt(t.tpe) })); tr.onclick = () => showTarget({ kind: 'symbol', symbol: t.s }); tb.append(tr); });
  tbl.append(tb); tt.append(el('div', { class: 'table-wrap' }, tbl)); host.append(tt);
  host.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
async function renderSymbolResult(sym) {
  const host = $('#peResult'); const V = S.valuation; let r = V && V.tickers && V.tickers[sym]; let live = null; let compactRow = null;
  if (S.live) { live = await apiLookup(sym); if (live && live.record) { r = live.record; sym = live.symbol || sym; } }
  if (!r) { await loadUniverse(); const u = S.universe && S.universe[sym]; if (u) { compactRow = u; r = { n: u[0], x: u[1], p: u[2], c: u[3], mc: u[4], fpe: u[5], tpe: u[6], ma50: u[7], ma200: u[8], ix: u[9] }; } }
  host.textContent = '';
  if (!r) { host.append(el('div', { class: 'empty' }, `找不到「${sym}」。`, el('br'), el('span', { class: 'hint', text: S.live ? '請確認代號（Yahoo 格式：台股 2330.TW、港股 0700.HK）。' : '靜態頁面只含每日抓取的名單；把代號加入 config/watchlist.txt 後隔天會出現，或在本機執行 python3 pipeline/serve.py 即時查詢任何代號。' }))); return; }
  const head = el('div', { class: 'result-head' }); head.append(el('span', { class: 'sym', text: sym }), el('span', { class: 'nm', text: `${r.n || ''} · ${r.x || ''}${r.sec ? ' · ' + r.sec : ''}` }));
  if (live) head.append(el('span', { class: 'badge live', text: '即時' })); if (r.sus) head.append(el('span', { class: 'badge warn', text: 'EPS 資料可疑' }));
  const px = el('span', { class: 'px', text: fmt(r.p, 2) }); px.append(el('small', { class: dir(r.c), text: signed(r.c, 2, '%') })); head.append(px); host.append(head);
  const chips = el('div', { class: 'chips' }); (r.ix || []).forEach(k => { const c = el('span', { class: 'chip', text: (S.byKey[k] && S.byKey[k].name) || k }); c.onclick = () => showTarget({ kind: 'index', key: k }); chips.append(c); }); if (chips.childElementCount) host.append(chips);
  const tiles = el('div', { class: 'grid kpi', style: 'margin:12px 0' });
  tiles.append(tile(`Forward PE（下一財年${r.fy1 ? ' ' + r.fy1.slice(0, 4) : ''}）`, peFmt(r.fpe), isNum(r.fe) ? `EPS 預估 ${fmt(r.fe, 2)}` : null, null, { hero: true }));
  tiles.append(tile('NTM PE（混合 12 個月）', peFmt(r.ntm), isNum(r.ne) ? `NTM EPS ${fmt(r.ne, 2)}（本財年權重 ${fmt(r.w, 2)}）` : (compactRow ? '需分析師預估（每日名單或即時查詢）' : '無分析師預估'), '最接近 Bloomberg BEst P/E'));
  tiles.append(tile('Trailing PE', peFmt(r.tpe), isNum(r.te) ? `TTM EPS ${fmt(r.te, 2)}` : null));
  tiles.append(tile('本財年 EPS 共識', isNum(r.e0) ? fmt(r.e0, 2) : '—', r.fy ? `財年至 ${r.fy}` : null, isNum(r.na) ? `${r.na} 位分析師` : null));
  tiles.append(tile('下一財年 EPS 共識', isNum(r.e1) ? fmt(r.e1, 2) : '—', isNum(r.rev90) ? `90 日修正 ${signed(r.rev90, 1, '%')}` : null, isNum(r.rev30) ? `30 日修正 ${signed(r.rev30, 1, '%')}` : null, { deltaClass: dir(r.rev90) }));
  tiles.append(tile('市值', compact(r.mc) + (r.cur ? ' ' + r.cur : ''), isNum(r.pb) ? `股價淨值比 ${fmt(r.pb, 2)}` : null, isNum(r.peg) ? `PEG ${fmt(r.peg, 2)}` : null));
  tiles.append(tile('相對 200 日線', isNum(r.p) && isNum(r.ma200) ? signed((r.p / r.ma200 - 1) * 100, 1, '%') : '—', isNum(r.ma50) ? `50 日 ${fmt(r.ma50, 2)}` : null, isNum(r.ma200) ? `200 日 ${fmt(r.ma200, 2)}` : null));
  tiles.append(tile('52 週區間', isNum(r.l52) ? `${fmt(r.l52, 2)}–${fmt(r.h52, 2)}` : '—', isNum(r.h52) && isNum(r.p) ? `距高點 ${signed((r.p / r.h52 - 1) * 100, 1, '%')}` : null, r.nx ? `下次財報 ${r.nx}` : null));
  host.append(tiles);
  const rows = (live && live.history) || S.tickerHist.get(sym) || [];
  if (rows.length) chartCard(host, `${sym} PE 歷史`, `每日快照累積（${rows.length} 日）`, { height: 220, yFmt: v => fmt(v, 1), range: '2Y' }, peHistorySeries(rows));
  else host.append(el('p', { class: 'hint', text: '此代號不在每日 PE 歷史名單內（S&P 500 / NASDAQ 100 / 道瓊 / SOX 成分股與 watchlist 才會每日累積）。' }));
  if (live && live.chart) chartCard(host, '股價（1 年）', sym, { height: 200, yFmt: v => fmt(v, v > 1000 ? 0 : 2), range: '1Y', area: true }, [{ name: sym, dates: live.chart.dates, values: live.chart.close, color: seriesColor(0), fmt: v => fmt(v, 2) }]);
  host.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
function renderWatchlist() {
  const host = $('#watchTable'); host.textContent = ''; const L = S.latest; if (!L || !L.watchlist || !L.watchlist.length) return;
  const tbl = el('table', { class: 'data' }); const hr = el('tr'); ['代號', '名稱', '價格', '今日', 'Fwd PE', 'NTM PE', 'Trailing PE', '下一財年 EPS', '90 日修正', '下次財報'].forEach(h => hr.append(el('th', { text: h }))); tbl.append(el('thead', {}, hr)); const tb = el('tbody');
  L.watchlist.forEach(w => { const tr = el('tr', { class: 'clickable' }); tr.append(el('td', { text: w.s }), el('td', { class: 'name', text: (w.n || '').slice(0, 30) }), el('td', { text: fmt(w.p, 2) }), el('td', { text: signed(w.c, 2, '%'), class: dir(w.c) === 'up' ? 'pos' : dir(w.c) === 'down' ? 'neg' : '' }), el('td', { text: peFmt(w.fpe) }), el('td', { text: peFmt(w.ntm) }), el('td', { text: peFmt(w.tpe) }), el('td', { text: fmt(w.e1, 2) }), el('td', { text: signed(w.rev90, 1, '%'), class: dir(w.rev90) === 'up' ? 'pos' : dir(w.rev90) === 'down' ? 'neg' : '' }), el('td', { text: w.nx || '—' })); tr.onclick = () => showTarget({ kind: 'symbol', symbol: w.s }); tb.append(tr); });
  tbl.append(tb); host.append(el('div', { class: 'table-wrap' }, tbl));
}
function renderFooter() {
  const st = S.status || (S.latest && S.latest.status) || {}; const f = $('#statusList'); f.textContent = '';
  f.append(el('li', { text: `產生時間 ${st.generated_at || '—'} UTC · 報價 ${st.symbols_quoted ?? '—'} 檔 · 參與度 ${st.symbols_breadth ?? '—'} 檔 · 分析師預估 ${st.estimates ?? '—'} 檔 · 耗時 ${st.total_seconds ?? '—'} 秒${st.quick ? '（快速模式）' : ''}` }));
  Object.entries(st.sources || {}).forEach(([k, v]) => f.append(el('li', { text: `成分股 ${k}: ${v}` })));
}

/* ------------------------------------------------------------ 分頁與初始化 */
function initTabs() {
  const show = id => { $$('nav.tabs button').forEach(b => b.setAttribute('aria-selected', b.dataset.tab === id ? 'true' : 'false')); $$('section.panel').forEach(s => s.classList.toggle('active', s.id === 'tab-' + id)); CHARTS.forEach(c => c.render()); };
  $$('nav.tabs button').forEach(b => { b.onclick = () => { show(b.dataset.tab); try { history.replaceState(null, '', '#' + b.dataset.tab); } catch (e) { } }; });
  const h = location.hash.replace('#', ''); const id = h.split('?')[0]; show(['report', 'breadth', 'rates', 'pe', 'vol'].includes(id) ? id : 'report');
  const q = new URLSearchParams(h.split('?')[1] || '').get('q'); if (q) { $('#peQuery').value = q; loadUniverse().then(() => { const r = resolveQuery(q); if (r) showTarget(r); }); }
}
function initTheme() {
  let t = null; try { t = localStorage.getItem('fh-theme'); } catch (e) { }
  if (t) document.documentElement.dataset.theme = t;
  $('#themeBtn').onclick = () => { const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'); const next = cur === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = next; try { localStorage.setItem('fh-theme', next); } catch (e) { } CHARTS.forEach(c => c.render()); };
}
async function main() {
  initTheme(); await loadAll();
  renderHeader(); renderOverview(); renderReport(); renderBreadth(); renderRates(); renderVol(); indexPeTable(); renderWatchlist(); renderFooter(); initSearch(); initInfo(); initTabs();
}
main().catch(e => { console.error(e); const o = $('#overview'); if (o) o.textContent = '載入失敗：' + e.message; });
})();
