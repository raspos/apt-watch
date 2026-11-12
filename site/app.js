'use strict';
const get = id => document.getElementById(id);
const nf = n => Number(n).toLocaleString('ko-KR');
let data;
const state = {metric: 'price', range: 0};

/* ---------- 날짜·숫자 표시 ---------- */
const pad = n => String(n).padStart(2, '0');
function kst(iso) {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : new Date(d.getTime() + (d.getTimezoneOffset() + 540) * 60000);
}
const fmtDate = iso => { const k = kst(iso); return k ? `${k.getFullYear()}-${pad(k.getMonth() + 1)}-${pad(k.getDate())}` : (iso ? String(iso).slice(0, 10) : ''); };
const fmtDateTime = iso => { const k = kst(iso); return k ? `${fmtDate(iso)} ${pad(k.getHours())}:${pad(k.getMinutes())}` : (iso ? String(iso).replace('T', ' ').slice(0, 16) : ''); };
const signed = (v, unit = '%') => (v > 0 ? '+' : '') + v.toFixed(1) + unit;
const dirClass = v => v > 0 ? 'up' : v < 0 ? 'down' : '';
function cell(tr, value, cls) {
  const td = document.createElement('td');
  td.textContent = value == null ? '–' : value;
  td.className = value == null ? 'na' : (cls || '');
  tr.append(td);
}

/* ---------- 차트 (공통 규칙: 선 2px, 격자 --line, 보간 없음, 잠정 점선) ---------- */
const FONT = '12px -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard","Noto Sans KR","Malgun Gothic",sans-serif';
const charts = [];
function dayNum(s) { return Math.round(Date.parse(s + 'T00:00:00Z') / 86400000); }
function monthNum(s) { const [y, m] = s.split('-'); return Number(y) * 12 + Number(m); }

function makeChart(cfg) {
  const canvas = get(cfg.canvas), readout = get(cfg.readout), ctx = canvas.getContext('2d');
  let pts = [], hover = -1;
  const empty = document.createElement('div');
  empty.className = 'empty'; empty.hidden = true;
  canvas.parentNode.insertBefore(empty, canvas);
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const geo = () => ({w: canvas.clientWidth, h: canvas.clientHeight, left: 44, right: 10, top: 12, bottom: 22});
  const connected = (a, b) => cfg.daily() ? dayNum(b.key) - dayNum(a.key) === 1 : monthNum(b.key) - monthNum(a.key) === 1;

  function load() {
    const all = cfg.points();
    const m = state.range;
    if (!m || !all.length || !cfg.ranged) return all;
    if (cfg.daily()) {
      const c = new Date(all.at(-1).key + 'T00:00:00Z'); c.setUTCMonth(c.getUTCMonth() - m);
      const cut = c.toISOString().slice(0, 10);
      return all.filter(p => p.key >= cut);
    }
    return all.slice(-m);
  }
  const xAt = (i, g) => g.left + i * (g.w - g.left - g.right) / Math.max(1, pts.length - 1);

  function draw() {
    if (!data) return;
    pts = load();
    canvas.setAttribute('aria-label', cfg.label());
    if (!pts.length) {
      canvas.hidden = true; empty.hidden = false; empty.textContent = cfg.emptyText();
      readout.textContent = ''; return;
    }
    canvas.hidden = false; empty.hidden = true;
    const g = geo(), ratio = window.devicePixelRatio || 1;
    canvas.width = g.w * ratio; canvas.height = g.h * ratio;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    const vals = pts.filter(p => p.value !== null).map(p => p.value);
    if (cfg.baseline != null) vals.push(cfg.baseline);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    const padv = (hi - lo || 2) * 0.12; lo -= padv; hi += padv;
    const y = v => g.top + (hi - v) * (g.h - g.top - g.bottom) / (hi - lo);
    ctx.font = FONT; ctx.textBaseline = 'alphabetic';
    ctx.fillStyle = css('--ink-3'); ctx.strokeStyle = css('--line'); ctx.lineWidth = 1; ctx.setLineDash([]);
    for (let i = 0; i < 4; i++) {
      const v = lo + (hi - lo) * i / 3, at = y(v);
      ctx.textAlign = 'right'; ctx.fillText(v.toFixed(cfg.digits), g.left - 6, at + 4);
      ctx.beginPath(); ctx.moveTo(g.left, at); ctx.lineTo(g.w - g.right, at); ctx.stroke();
    }
    if (cfg.baseline != null) {
      ctx.strokeStyle = css('--ink-3'); ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(g.left, y(cfg.baseline)); ctx.lineTo(g.w - g.right, y(cfg.baseline)); ctx.stroke(); ctx.setLineDash([]);
    }
    ctx.fillStyle = css('--ink-3');
    ctx.textAlign = 'left'; ctx.fillText(pts[0].key, g.left, g.h - 4);
    ctx.textAlign = 'right'; ctx.fillText(pts.at(-1).key, g.w - g.right, g.h - 4);
    const ink = css('--ink');
    ctx.strokeStyle = ink; ctx.fillStyle = ink; ctx.lineWidth = 2;
    pts.forEach((p, i) => {
      if (p.value === null) return;
      const prev = pts[i - 1];
      if (prev && prev.value !== null && connected(prev, p)) {
        ctx.setLineDash(p.provisional ? [4, 4] : []);
        ctx.beginPath(); ctx.moveTo(xAt(i - 1, g), y(prev.value)); ctx.lineTo(xAt(i, g), y(p.value)); ctx.stroke();
      } else {
        ctx.beginPath(); ctx.arc(xAt(i, g), y(p.value), 2.5, 0, Math.PI * 2); ctx.fill();
      }
    });
    ctx.setLineDash([]);
    const at = hover >= 0 && hover < pts.length ? hover : pts.length - 1;
    const hp = pts[at];
    if (hp.value !== null) {
      ctx.strokeStyle = css('--ink-3'); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(xAt(at, g), g.top); ctx.lineTo(xAt(at, g), g.h - g.bottom); ctx.stroke();
      ctx.fillStyle = ink; ctx.beginPath(); ctx.arc(xAt(at, g), y(hp.value), 4, 0, Math.PI * 2); ctx.fill();
    }
    readout.textContent = cfg.read(hp);
  }
  function setHover(e) {
    if (!pts.length) return;
    const g = geo(), x = e.clientX - canvas.getBoundingClientRect().left;
    hover = Math.max(0, Math.min(pts.length - 1, Math.round((x - g.left) / (g.w - g.left - g.right) * (pts.length - 1))));
    draw();
  }
  canvas.addEventListener('pointermove', setHover);
  canvas.addEventListener('pointerdown', setHover);
  canvas.addEventListener('pointerleave', () => { hover = -1; draw(); });
  canvas.addEventListener('keydown', e => {
    if (!pts.length || (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight')) return;
    const cur = hover >= 0 ? hover : pts.length - 1;
    hover = Math.max(0, Math.min(pts.length - 1, cur + (e.key === 'ArrowRight' ? 1 : -1)));
    e.preventDefault(); draw();
  });
  new ResizeObserver(() => draw()).observe(canvas);
  const api = {draw, reset() { hover = -1; }};
  charts.push(api);
  return api;
}

const code = () => get('district').value;
const region = () => data.market.regions[code()] || data.market.regions.all;

const chart1 = makeChart({
  canvas: 'chart', readout: 'readout', ranged: true, digits: 0, baseline: 100,
  daily: () => state.metric === 'ask',
  label: () => state.metric === 'ask' ? '일별 동일 매물 호가지수' : '월별 실거래가격지수',
  emptyText: () => '관측 자료 부족으로 미산출',
  points: () => state.metric === 'ask'
    ? (region().askingSeries || []).map(p => ({key: p.day, value: p.index, samples: p.matched}))
    : (data.series[code()] || []).map(p => ({key: p.month, value: p.index, samples: p.samples, matched: p.matched, modelGroups: p.modelGroups, provisional: p.provisional, withheld: p.withheld})),
  read: p => state.metric === 'ask'
    ? `${p.key} · 호가지수 ${p.value === null ? '미산출' : p.value.toFixed(2)} · 비교 매물 ${nf(p.samples)}건 · 첫 관측일 = 100`
    : `${p.key} · ${p.value === null ? (p.withheld || '표본 부족으로 미산출') : p.value.toFixed(2)} · 거래 ${nf(p.samples)}건 · 비교 표본 ${nf(p.matched)}개` + (p.modelGroups != null ? ` · 모형 그룹 ${nf(p.modelGroups)}개` : '') + (p.provisional ? ' · 잠정' : '')
});
const chart2 = makeChart({
  canvas: 'chart2', readout: 'readout2', ranged: false, digits: 1, baseline: 0,
  daily: () => true,
  label: () => '관측일별 가격괴리율',
  emptyText: () => {
    const sp = data.market.regions.all.spread;
    return '관측일별 괴리율 이력은 비교 표본이 확보된 날부터 쌓입니다.' + (sp && sp.percent != null ? ` 현재 참고 괴리율 ${signed(sp.percent)} (대표지수 아님)` : '');
  },
  points: () => (data.market.spreadHistory?.[code()] || []).map(p => ({key: p.day, value: p.percent, samples: p.sample})),
  read: p => `${p.key} · 괴리율 ${p.value === null ? '미산출' : signed(p.value)} · 비교 그룹 ${nf(p.samples)}개`
});

/* ---------- 카드·표 ---------- */
function setTile(id, value, wip) { const el = get(id); el.textContent = value; el.className = 'v' + (wip ? ' wip' : ''); }
function setRef(id, text) { const el = get(id); el.hidden = !text; el.textContent = text || ''; }

function renderMarket() {
  const all = data.market.regions.all;
  const a = data.asking || {};
  const asof = a.lastSuccess ? fmtDate(a.lastSuccess) : fmtDate(data.market.day);
  const days = (all.askingSeries || []).length;
  const actualDistricts = Object.entries(data.market.regions).filter(([c, r]) => c !== 'all' && (r.spread?.status === '실측' || (r.spread?.percent != null && r.spread?.status !== '장기 실측 참고치'))).length;
  const longDistricts = Object.entries(data.market.regions).filter(([c, r]) => c !== 'all' && r.spread?.status === '장기 실측 참고치').length;

  get('marketState').textContent = data.market.state || '';

  /* 가격괴리지수: 대표지수 공표 전에는 참고치를 작은 보조 줄로만 */
  const sp = all.spread;
  setTile('premium', '데이터 축적 중', true);
  setRef('premiumRef', sp && sp.percent != null
    ? `참고 괴리율 ${signed(sp.percent)} · 90일 실거래 ${actualDistricts}개 구 · 180일 실거래 ${longDistricts}개 구 (비교 ${nf(sp.sample)}개 그룹 · 대표지수 아님)` : '');
  get('premiumAsof').textContent = `기준일 ${asof}`;

  /* 호가조정지수 */
  const c1 = all.concessions?.['1'] || {}, c7 = all.concessions?.['7'] || {};
  const cc = c1.sample >= 10 && c1.cutShare != null ? c1 : (c7.sample >= 10 && c7.cutShare != null ? c7 : null);
  if (cc) {
    const net = (cc.riseShare || 0) - (cc.cutShare || 0);
    setTile('cuts', signed(net, '%p'), false);
    get('cuts').classList.add(dirClass(net) || 'flat');
    setRef('cutRef', `인하 ${cc.cutShare.toFixed(1)}% · 인상 ${(cc.riseShare || 0).toFixed(1)}% · 연속 관측 ${nf(cc.sample)}건`);
  } else {
    setTile('cuts', '데이터 축적 중', true);
    setRef('cutRef', `관측 ${days}일차 · 기준선 ${nf(a.listings || 0)}건 등록 · 연속 관측 대기`);
  }
  get('cutAsof').textContent = `기준일 ${asof}`;

  /* 거래활력지수 */
  const ab = all.absorption, prov = all.provisionalAbsorption;
  if (ab && ab.percent != null) {
    setTile('absorption', `100건당 ${ab.percent.toFixed(1)}건`, false);
    setRef('absorptionRef', `30일 계약 ${nf(ab.tradeCount)}건 ÷ 일평균 매물 ${nf(Math.round(ab.meanDailyListings))}건`);
  } else if (prov && prov.percent != null) {
    setTile('absorption', `100건당 ${prov.percent.toFixed(1)}건`, false);
    get('absorption').insertAdjacentHTML('beforeend', '<span class="badge">잠정</span>');
    setRef('absorptionRef', '신고 시차(최대 30일) 반영 중');
  } else {
    setTile('absorption', '데이터 축적 중', true);
    setRef('absorptionRef', `30일 관측 패널 확보 전 · 추적 매물 ${nf(a.listings || 0)}건`);
  }
  get('absorptionAsof').textContent = `기준일 ${asof}`;

  /* 호가 인상·인하 섹션 */
  const ten = data.market.pressure?.tenure;
  const kv = [['관측 일차', `${days}일차`], ['관측 단지', `${nf(a.successes || 0)}개`], ['추적 매물', `${nf(a.listings || 0)}건`], ['연속 관측 비교', `${nf(c1.sample || 0)}건`]];
  if (ten && ten.medianDays != null) kv.push(['중위 체류기간', `${ten.medianDays}일`]);
  get('adjKv').replaceChildren(...kv.map(([k, v]) => {
    const d = document.createElement('div'), s = document.createElement('span'), b = document.createElement('b');
    s.textContent = k; b.textContent = v; d.append(s, b); return d;
  }));

  /* 지역 표 */
  const actualCount = Object.values(data.market.regions).filter(r => r.spread?.status === '실측' || (r.spread?.percent != null && r.spread?.status !== '장기 실측 참고치')).length;
  const longCount = Object.values(data.market.regions).filter(r => r.spread?.status === '장기 실측 참고치').length;
  get('regionQ').textContent = `호가 관측 25개 구 (${nf(a.successes || 0)}개 단지) · 가격괴리 관측 24개 구 (90일 실거래 ${actualCount} · 180일 실거래 ${longCount} · 비교자료 부족 1)`;
  const rank = get('ranking').value;
  const rows = Object.entries(data.districts).map(([c, name]) => {
    const r = data.market.regions[c] || {};
    const sp = r.spread || {};
    const act = sp.actual90d?.percent ?? sp.percent ?? null;
    const lng = sp.longTerm180d?.percent ?? null;
    const mdl = sp.modelEst?.percent ?? null;
    const status = sp.status || (act != null ? '90일 실거래' : lng != null ? '180일 실거래' : mdl != null ? '모형 추정' : '비교자료 부족');
    const displayVal = act != null ? act : lng != null ? lng : mdl != null ? mdl : null;
    const listingsCount = r.askingSeries?.[0]?.matched ?? 0;
    const compsCount = r.coverage?.roster ?? 0;
    
    return {
      code: c,
      name,
      listings: listingsCount,
      complexes: compsCount,
      cuts: r.concessions?.['7']?.cutShare ?? null,
      spread: displayVal,
      spreadAct: act,
      spreadLng: lng,
      spreadMdl: mdl,
      status: (status === '실측' ? '90일 실거래' : status === '장기 실측 참고치' ? '180일 실거래' : status === '데이터 부족' ? '비교자료 부족' : status),
      statusCode: sp.statusCode,
      reason: sp.reason,
      absorption: r.absorption?.percent ?? null
    };
  });
  if (rank === 'district') {
    rows.sort((x, y) => x.name.localeCompare(y.name, 'ko'));
  } else if (rank === 'spread') {
    rows.sort((x, y) => (y.spread ?? -Infinity) - (x.spread ?? -Infinity) || x.name.localeCompare(y.name, 'ko'));
  } else if (rank === 'listings') {
    rows.sort((x, y) => (y.listings ?? -Infinity) - (x.listings ?? -Infinity) || x.name.localeCompare(y.name, 'ko'));
  } else {
    rows.sort((x, y) => (y[rank] ?? -Infinity) - (x[rank] ?? -Infinity) || x.name.localeCompare(y.name, 'ko'));
  }
  get('districtRows').replaceChildren(...rows.map(row => {
    const tr = document.createElement('tr');
    cell(tr, row.name);
    
    const tdObs = document.createElement('td');
    tdObs.textContent = `${row.complexes}단지 ${nf(row.listings)}건`;
    tr.appendChild(tdObs);
    
    const tdCut = document.createElement('td');
    if (row.cuts != null) {
      tdCut.textContent = row.cuts.toFixed(1) + '%';
    } else {
      tdCut.textContent = '2회차 대기';
      tdCut.className = 'na';
    }
    tr.appendChild(tdCut);
    
    const tdSpread = document.createElement('td');
    if (row.spread != null) {
      const valSpan = document.createElement('span');
      valSpan.textContent = signed(row.spread);
      valSpan.className = dirClass(row.spread);
      tdSpread.appendChild(valSpan);
      
      const badge = document.createElement('span');
      if (row.status === '90일 실거래') {
        badge.className = 'badge badge-actual';
        badge.textContent = '90일 실거래';
      } else if (row.status === '180일 실거래') {
        badge.className = 'badge badge-long';
        badge.textContent = '180일 실거래';
      } else if (row.status === '모형 추정') {
        badge.className = 'badge badge-model';
        badge.textContent = '모형 추정';
      }
      if (row.reason) badge.title = row.reason;
      tdSpread.appendChild(badge);
    } else {
      const badge = document.createElement('span');
      badge.className = 'badge badge-muted';
      badge.textContent = '비교자료 부족';
      if (row.reason) badge.title = row.reason;
      tdSpread.appendChild(badge);
    }
    tr.appendChild(tdSpread);
    
    const tdAbs = document.createElement('td');
    if (row.absorption != null) {
      tdAbs.textContent = row.absorption.toFixed(1) + '%';
    } else {
      tdAbs.textContent = '30일 대기';
      tdAbs.className = 'na';
    }
    tr.appendChild(tdAbs);
    
    return tr;
  }));
}

/* ---------- 컨트롤 ---------- */
function bindSeg(id, attr, onPick) {
  get(id).addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    get(id).querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    onPick(b.dataset[attr]);
  });
}
bindSeg('metricSeg', 'metric', v => { state.metric = v; chart1.reset(); chart1.draw(); });
bindSeg('rangeSeg', 'range', v => { state.range = Number(v); chart1.draw(); });
get('district').onchange = () => charts.forEach(c => { c.reset(); c.draw(); });
get('ranking').onchange = () => { if (data) renderMarket(); };

/* 테마: 시스템 설정을 따르되 버튼으로 덮어쓰기 */
const mq = window.matchMedia('(prefers-color-scheme: dark)');
const effectiveTheme = () => document.documentElement.dataset.theme || (mq.matches ? 'dark' : 'light');
try { const t = localStorage.getItem('watch-theme'); if (t === 'dark' || t === 'light') document.documentElement.dataset.theme = t; } catch (e) {}
get('theme').onclick = () => {
  const next = effectiveTheme() === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('watch-theme', next); } catch (e) {}
  charts.forEach(c => c.draw());
};
mq.addEventListener?.('change', () => charts.forEach(c => c.draw()));

/* 방법론은 모바일에서 접힌 채 시작 */
if (window.matchMedia('(min-width:761px)').matches) get('method').open = true;

fetch('./data.json').then(r => { if (!r.ok) throw Error(); return r.json(); }).then(value => {
  data = value;
  for (const [c, name] of Object.entries(data.districts)) get('district').add(new Option(name, c));
  const a = data.asking || {};
  get('meta').replaceChildren(...[
    ['실거래 갱신', `${fmtDateTime(data.asOf)} KST`],
    ['호가 관측', a.lastSuccess ? `${fmtDate(a.lastSuccess)} · ${nf(a.successes)}개 단지 ${nf(a.listings)}건` : '자료 없음']
  ].map(([k, v]) => { const s = document.createElement('span'), b = document.createElement('b'); s.append(k + ' '); b.textContent = v; s.append(b); return s; }));
  renderMarket();
  get('coverage').textContent = `${nf(data.districtMonths)}개 구·월 · 원자료 ${nf(data.raw)}건 · 분석 대상 ${nf(data.eligibleTrades)}건 · ${data.version}`;
  get('chartNote').textContent = '점선은 잠정 구간(신고 시차 미반영), 끊긴 선은 자료가 없는 기간입니다. 지수는 기준 시점 = 100.';
  charts.forEach(c => c.draw());
}).catch(() => { get('meta').textContent = '자료를 불러오지 못했습니다.'; });
