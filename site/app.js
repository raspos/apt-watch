'use strict';
const get = id => document.getElementById(id);
const nf = n => Number(n).toLocaleString('ko-KR');
let data;
const state = {metric: 'price', range: 0, selectedDate: null};
const mapState = {mode: 'spread', selectedCode: '11680'};

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
const charts = [];
function dayNum(s) { return Math.round(Date.parse(s + 'T00:00:00Z') / 86400000); }
function monthNum(s) { const [y, m] = s.split('-'); return Number(y) * 12 + Number(m); }

function makeChart(cfg) {
  const canvas = get(cfg.canvas), readout = get(cfg.readout), ctx = canvas.getContext('2d');
  let pts = [], hover = -1;
  const empty = document.createElement('div');
  empty.className = 'empty'; empty.hidden = true;
  canvas.parentNode.insertBefore(empty, canvas);
  const geo = () => ({w: canvas.clientWidth, h: canvas.clientHeight, left: 44, right: 10, top: 12, bottom: 22});

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

  const isDaily = cfg.daily();
  const timeOf = k => {
    if (!k) return 0;
    return Date.parse(k.length === 10 ? k + 'T00:00:00Z' : k + '-01T00:00:00Z');
  };
  const xAt = (i, g) => {
    if (!pts.length) return g.left;
    if (isDaily && pts.length > 1) {
      const tMin = timeOf(pts[0].key), tMax = timeOf(pts.at(-1).key);
      if (tMax > tMin) {
        return g.left + ((timeOf(pts[i].key) - tMin) / (tMax - tMin)) * (g.w - g.left - g.right);
      }
    }
    return g.left + i * (g.w - g.left - g.right) / Math.max(1, pts.length - 1);
  };

  function draw() {
    if (!data) return;
    pts = load();
    canvas.setAttribute('aria-label', cfg.label());
    if (!pts.length) {
      canvas.hidden = true; empty.hidden = false; empty.textContent = cfg.emptyText();
      readout.textContent = ''; return;
    }
    canvas.hidden = false; empty.hidden = true;
    const g = geo();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = g.w * dpr; canvas.height = g.h * dpr;
    ctx.resetTransform?.(); ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, g.w, g.h);

    const vals = pts.map(p => p.value).filter(v => v !== null);
    if (!vals.length) {
      canvas.hidden = true; empty.hidden = false; empty.textContent = cfg.emptyText();
      return;
    }
    let minV = Math.min(...vals), maxV = Math.max(...vals);
    if (cfg.baseline != null) { minV = Math.min(minV, cfg.baseline); maxV = Math.max(maxV, cfg.baseline); }
    const span = Math.max(0.001, maxV - minV);
    const yAt = v => g.h - g.bottom - ((v - minV) / span) * (g.h - g.top - g.bottom);

    const isDark = document.documentElement.dataset.theme === 'dark' ||
      (!document.documentElement.dataset.theme && window.matchMedia('(prefers-color-scheme: dark)').matches);
    const lineClr = isDark ? '#34342f' : '#e6e6e2';
    const textClr = isDark ? '#888880' : '#888880';
    const accentClr = isDark ? '#eb6834' : '#d95926';

    // Baseline & Grid
    ctx.strokeStyle = lineClr; ctx.lineWidth = 1; ctx.setLineDash([]);
    if (cfg.baseline != null) {
      const by = yAt(cfg.baseline);
      ctx.beginPath(); ctx.moveTo(g.left, by); ctx.lineTo(g.w - g.right, by); ctx.stroke();
    }
    ctx.beginPath(); ctx.moveTo(g.left, g.top); ctx.lineTo(g.left, g.h - g.bottom); ctx.stroke();

    // Data Line: Draw solid for continuous days, dashed across unobserved date gaps (>1.5 days)
    let prevValid = -1;
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i];
      if (p.value === null) {
        prevValid = -1;
        continue;
      }
      if (prevValid !== -1) {
        const x1 = xAt(prevValid, g), y1 = yAt(pts[prevValid].value);
        const x2 = xAt(i, g), y2 = yAt(p.value);
        let hasGap = false;
        if (isDaily) {
          const dayGap = (timeOf(p.key) - timeOf(pts[prevValid].key)) / 86400000;
          if (dayGap > 1.5) hasGap = true;
        }
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        if (hasGap) {
          ctx.save();
          ctx.setLineDash([3, 3]);
          ctx.strokeStyle = isDark ? '#666660' : '#a0a098';
          ctx.lineWidth = 1.5;
          ctx.stroke();
          ctx.restore();
        } else {
          ctx.save();
          ctx.setLineDash([]);
          ctx.strokeStyle = accentClr;
          ctx.lineWidth = 2;
          ctx.stroke();
          ctx.restore();
        }
      }
      prevValid = i;
    }

    // Points
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i];
      if (p.value === null) continue;
      const x = xAt(i, g), y = yAt(p.value);
      ctx.fillStyle = i === hover ? (isDark ? '#ffffff' : '#111111') : accentClr;
      ctx.beginPath(); ctx.arc(x, y, i === hover ? 4 : 2, 0, Math.PI * 2); ctx.fill();
    }

    const last = pts.at(-1);
    if (last && last.value !== null) readout.textContent = cfg.read(last);
  }

  canvas.addEventListener('mousemove', e => {
    const rect = canvas.getBoundingClientRect(), g = geo();
    const x = e.clientX - rect.left;
    let closest = -1, dist = 999;
    for (let i = 0; i < pts.length; i++) {
      const px = xAt(i, g);
      if (Math.abs(x - px) < dist) { dist = Math.abs(x - px); closest = i; }
    }
    if (closest !== hover && closest !== -1 && pts[closest].value !== null) {
      hover = closest; draw();
      readout.textContent = cfg.read(pts[hover]);
    }
  });
  canvas.addEventListener('mouseleave', () => { hover = -1; draw(); });

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
    const sp = data.market.regions.all?.spread;
    return '관측일별 괴리율 이력은 비교 표본이 확보된 날부터 쌓입니다.' + (sp && sp.percent != null ? ` 현재 참고 괴리율 ${signed(sp.percent)} (대표지수 아님)` : '');
  },
  points: () => (data.market.spreadHistory?.[code()] || []).map(p => {
    const v = p.actual90d?.percent ?? p.percent ?? p.longTerm180d?.percent ?? null;
    const is180 = (p.status === '장기 실측 참고치' || (p.longTerm180d?.percent != null && p.actual90d?.percent == null));
    const samp = is180 ? (p.longTerm180d?.sample ?? 0) : (p.actual90d?.sample ?? p.sample ?? 0);
    return {key: p.day, value: v, samples: samp, status: p.status};
  }),
  read: p => `${p.key} · 괴리율 ${p.value === null ? '미산출' : signed(p.value)} · 비교 그룹 ${nf(p.samples)}개` + (p.status ? ` (${p.status})` : '')
});

/* ==========================================================================
   서울 25개 구 시장심리 지도 (Interactive Map)
   ========================================================================== */

function getRegionData(c, targetDate = state.selectedDate) {
  if (!data || !data.market) return {};
  const currentDay = data.market.day;
  const base = data.market.regions[c] || {};
  if (!targetDate || targetDate === currentDay) {
    return base;
  }
  const snap = data.market.dailySnapshots?.[targetDate]?.[c];
  if (snap) {
    return { ...base, spread: snap };
  }
  return base;
}

function getAllSpread(targetDate = state.selectedDate) {
  if (!data || !data.market) return null;
  const currentDay = data.market.day;
  if (!targetDate || targetDate === currentDay) {
    return data.market.regions.all?.spread?.percent ?? null;
  }
  const snap = data.market.dailySnapshots?.[targetDate]?.all;
  return snap ? (snap.percent ?? null) : (data.market.regions.all?.spread?.percent ?? null);
}

function getDivergingColor(pct, isDark) {
  if (pct == null) return isDark ? '#262624' : '#deded9';
  if (pct >= -0.5 && pct <= 0.5) return isDark ? '#2d2d2a' : '#edece8';

  if (pct > 0) {
    if (pct < 3.0) return isDark ? '#4d271a' : '#fddcd2';
    if (pct < 6.0) return isDark ? '#78341f' : '#f9b6a0';
    if (pct < 10.0) return isDark ? '#a84524' : '#f1845c';
    if (pct < 15.0) return isDark ? '#d95926' : '#e65928';
    return isDark ? '#eb6834' : '#c73d10';
  } else {
    if (pct > -3.0) return isDark ? '#172d47' : '#d5e5fa';
    if (pct > -6.0) return isDark ? '#1f4575' : '#a4c7f4';
    if (pct > -10.0) return isDark ? '#2a61a6' : '#679fe8';
    return isDark ? '#3987e5' : '#2f78d6';
  }
}

function getVitalityColor(val, isDark) {
  if (val == null) return isDark ? '#262624' : '#deded9';
  if (val < 1.0) return isDark ? '#1a2e3b' : '#deebf7';
  if (val < 2.0) return isDark ? '#1e445d' : '#c6dbef';
  if (val < 3.0) return isDark ? '#235e82' : '#9ecae1';
  if (val < 5.0) return isDark ? '#2a7aa8' : '#6baed6';
  return isDark ? '#3599d1' : '#3182bd';
}

function renderSeoulMap() {
  const wrap = get('mapSvgWrap');
  if (!wrap || !window.SEOUL_DISTRICTS_SVG) return;

  const isDark = document.documentElement.dataset.theme === 'dark' ||
    (!document.documentElement.dataset.theme && window.matchMedia('(prefers-color-scheme: dark)').matches);

  const districtsSvg = window.SEOUL_DISTRICTS_SVG;
  let svgHtml = `<svg viewBox="0 0 640 520" class="map-svg" role="img" aria-label="서울시 25개 자치구 시장심리 지도">`;

  // Compute stats across all 25 districts for mode rendering
  const districtEntries = districtsSvg.map(d => {
    const c = d.code;
    const r = getRegionData(c);
    const sp = r.spread || {};
    const act = sp.actual90d?.percent ?? sp.percent ?? null;
    const lng = sp.longTerm180d?.percent ?? null;
    const status = sp.status;
    const displayVal = act != null ? act : lng;

    // Concession
    const c1 = r.concessions?.['1'] || {}, c7 = r.concessions?.['7'] || {};
    const cc = (c1.sample >= 10 && c1.cutShare != null) ? c1 : ((c7.sample >= 10 && c7.cutShare != null) ? c7 : (r.concessions?.['30']?.sample >= 10 ? r.concessions?.['30'] : null));
    const net = (cc && cc.cutShare != null) ? ((cc.riseShare || 0) - (cc.cutShare || 0)) : null;

    // Vitality
    const ab = r.absorption, prov = r.provisionalAbsorption;
    const vitVal = (ab && ab.percent != null) ? ab.percent : ((prov && prov.percent != null) ? prov.percent : null);

    return { code: c, svg: d, r, sp, act, lng, status, displayVal, cc, net, vitVal, isProv: (!ab || ab.percent == null) };
  });

  // 1. Path elements
  districtEntries.forEach(item => {
    const c = item.code;
    const d = item.svg;
    let fillClr, cls = ['district-path'];

    if (mapState.mode === 'spread') {
      if (item.status === '장기 실측 참고치' || (item.lng != null && item.act == null)) {
        cls.push('tier-180');
        fillClr = getDivergingColor(item.lng, isDark);
      } else if (item.status === '데이터 부족' || item.displayVal == null) {
        cls.push('tier-insufficient');
        fillClr = isDark ? '#262624' : '#deded9';
      } else {
        fillClr = getDivergingColor(item.act, isDark);
      }
    } else if (mapState.mode === 'concession') {
      if (item.net != null) {
        fillClr = getDivergingColor(item.net, isDark);
      } else {
        cls.push('tier-insufficient');
        fillClr = isDark ? '#262624' : '#deded9';
      }
    } else if (mapState.mode === 'vitality') {
      if (item.vitVal != null) {
        fillClr = getVitalityColor(item.vitVal, isDark);
        if (item.isProv) cls.push('tier-180');
      } else {
        cls.push('tier-insufficient');
        fillClr = isDark ? '#262624' : '#deded9';
      }
    }

    if (mapState.selectedCode === c) cls.push('selected');
    svgHtml += `<path class="${cls.join(' ')}" id="map-dist-${c}" data-code="${c}" data-name="${d.name}" d="${d.d}" fill="${fillClr}"></path>`;
  });

  // 2. Text Labels & Values
  districtEntries.forEach(item => {
    const d = item.svg;
    let valText = '';
    let valClr = isDark ? '#d4d4cc' : '#555550';

    if (mapState.mode === 'spread') {
      if (item.status === '데이터 부족' || item.displayVal == null) {
        valText = '부족';
        valClr = isDark ? '#888880' : '#888880';
      } else {
        valText = signed(item.displayVal);
        valClr = item.displayVal > 0 ? (isDark ? '#ff9a70' : '#b83e10') : (item.displayVal < 0 ? (isDark ? '#8ab4f8' : '#1a5ab0') : valClr);
      }
    } else if (mapState.mode === 'concession') {
      if (item.net != null) {
        valText = signed(item.net, '%p');
        valClr = item.net > 0 ? (isDark ? '#ff9a70' : '#b83e10') : (item.net < 0 ? (isDark ? '#8ab4f8' : '#1a5ab0') : valClr);
      } else {
        valText = '대기';
        valClr = isDark ? '#888880' : '#888880';
      }
    } else if (mapState.mode === 'vitality') {
      if (item.vitVal != null) {
        valText = `${item.vitVal.toFixed(1)}건${item.isProv ? '*' : ''}`;
        valClr = isDark ? '#d4d4cc' : '#333330';
      } else {
        valText = '대기';
        valClr = isDark ? '#888880' : '#888880';
      }
    }

    svgHtml += `<g class="district-text-group" pointer-events="none">
      <text class="district-label" x="${d.cx}" y="${d.cy - 6}">${d.name.replace('구', '')}</text>
      <text class="district-val" x="${d.cx}" y="${d.cy + 7}" fill="${valClr}">${valText}</text>
    </g>`;
  });

  svgHtml += `</svg>`;
  wrap.innerHTML = svgHtml;

  // Add click listeners to paths
  wrap.querySelectorAll('.district-path').forEach(p => {
    p.addEventListener('click', () => {
      const targetCode = p.dataset.code;
      selectDistrict(targetCode, true);
    });
  });

  renderMapLegend();
}

function selectDistrict(c, scrollTable = false) {
  mapState.selectedCode = c;

  // 1. Update Map SVG paths
  const wrap = get('mapSvgWrap');
  if (wrap) {
    wrap.querySelectorAll('.district-path').forEach(p => {
      p.classList.toggle('selected', p.dataset.code === c);
    });
  }

  // 2. Update Detail Card
  renderDistrictDetail(c);

  // 3. Update District Select in Series Section
  const sel = get('district');
  if (sel && sel.value !== c) {
    sel.value = c;
    charts.forEach(ch => { ch.reset(); ch.draw(); });
  }

  // 4. Highlight Table Row in Section 04
  const tbody = get('districtRows');
  if (tbody) {
    let matchedRow = null;
    tbody.querySelectorAll('tr').forEach(tr => {
      const isMatch = tr.dataset.code === c;
      tr.classList.toggle('row-selected', isMatch);
      if (isMatch) matchedRow = tr;
    });
    if (scrollTable && matchedRow) {
      matchedRow.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }
}

function renderMapLegend() {
  const el = get('mapLegend');
  if (!el || !data) return;

  const regions = Object.entries(data.market.regions).filter(([c]) => c !== 'all');
  const actualCount = regions.filter(([c]) => {
    const sp = getRegionData(c).spread || {};
    return sp.status === '실측' || (sp.actual90d?.percent != null);
  }).length;
  const longCount = regions.filter(([c]) => {
    const sp = getRegionData(c).spread || {};
    return sp.status === '장기 실측 참고치' || (sp.status !== '실측' && sp.longTerm180d?.percent != null);
  }).length;
  const insuffCount = regions.length - actualCount - longCount;

  if (mapState.mode === 'spread') {
    el.innerHTML = `
      <div class="legend-bar-wrap">
        <span style="font-size:10px;color:var(--down)">-10%</span>
        <div class="legend-bar"></div>
        <span style="font-size:10px;color:var(--up)">+15%</span>
      </div>
      <div class="legend-labels">
        <span>호가 &lt; 실거래 (낮음)</span>
        <span>0% 기준 (일치)</span>
        <span>호가 &gt; 실거래 (높음)</span>
      </div>
      <div class="legend-swatches">
        <span class="legend-swatch"><span class="swatch-box" style="background:#e65928"></span> 90일 실거래 (${actualCount}개 구)</span>
        <span class="legend-swatch"><span class="swatch-box tier-180"></span> 180일 실거래 (${longCount}개 구)</span>
        <span class="legend-swatch"><span class="swatch-box insufficient"></span> 비교자료 부족 (${insuffCount}개 구)</span>
      </div>
    `;
  } else if (mapState.mode === 'concession') {
    el.innerHTML = `
      <div class="legend-swatches" style="margin:0">
        <span class="legend-swatch"><span class="swatch-box" style="background:var(--up)"></span> 인상 우세</span>
        <span class="legend-swatch"><span class="swatch-box" style="background:var(--down)"></span> 인하 우세</span>
        <span class="legend-swatch"><span class="swatch-box" style="background:var(--surface-2)"></span> 변화 미미</span>
        <span class="legend-swatch"><span class="swatch-box insufficient"></span> 데이터 축적 중 (2회차 연속 관측 대기)</span>
      </div>
    `;
  } else if (mapState.mode === 'vitality') {
    el.innerHTML = `
      <div class="legend-swatches" style="margin:0">
        <span class="legend-swatch"><span class="swatch-box" style="background:#3182bd"></span> 활발 (3.0건 이상)</span>
        <span class="legend-swatch"><span class="swatch-box" style="background:#9ecae1"></span> 보통 (1.0~3.0건)</span>
        <span class="legend-swatch"><span class="swatch-box" style="background:#deebf7"></span> 둔화 (1.0건 미만)</span>
        <span class="legend-swatch"><span class="swatch-box insufficient"></span> 30일 패널 구축 중 (신고 시차 반영)</span>
      </div>
    `;
  }
}

function renderMapSummary() {
  const el = get('mapSummaryBar');
  if (!el || !data) return;

  const regions = Object.entries(data.market.regions).filter(([c]) => c !== 'all');
  const actualCount = regions.filter(([c]) => {
    const sp = getRegionData(c).spread || {};
    return sp.status === '실측' || (sp.actual90d?.percent != null);
  }).length;
  const longCount = regions.filter(([c]) => {
    const sp = getRegionData(c).spread || {};
    return sp.status === '장기 실측 참고치' || (sp.status !== '실측' && sp.longTerm180d?.percent != null);
  }).length;
  const insuffCount = regions.length - actualCount - longCount;

  const validSpreads = regions.map(([c]) => {
    const sp = getRegionData(c).spread || {};
    return sp.actual90d?.percent ?? sp.percent ?? sp.longTerm180d?.percent ?? null;
  }).filter(v => v != null);
  const upCount = validSpreads.filter(v => v > 0).length;
  const downCount = validSpreads.filter(v => v < 0).length;

  const allSpread = getAllSpread();

  el.innerHTML = `
    <div class="map-summary-item">
      <span>서울 자치구:</span> <b>총 ${regions.length}개 구</b>
    </div>
    <div class="map-summary-item">
      <span>실측 커버리지:</span> <b>90일 실거래 ${actualCount}</b> · <b>180일 실거래 ${longCount}</b> · <b>비교자료 부족 ${insuffCount}</b>
    </div>
    <div class="map-summary-item">
      <span>호가 수준:</span> <b>실거래 상회 ${upCount}개 구</b> · <b>하회 ${downCount}개 구</b>
    </div>
    <div class="map-summary-item">
      <span class="map-summary-pill active">참고 괴리율 ${allSpread != null ? signed(allSpread) : '산출 유보'}</span>
      <span style="font-size:11px;color:var(--ink-3)">(대표지수 아님)</span>
    </div>
  `;
}

function renderDistrictDetail(c) {
  const card = get('districtDetailCard');
  if (!card || !data) return;

  const name = data.districts[c] || '선택 지역';
  const r = getRegionData(c);
  const sp = r.spread || {};
  const act = sp.actual90d?.percent ?? sp.percent ?? null;
  const lng = sp.longTerm180d?.percent ?? null;
  const displayVal = act != null ? act : lng;

  const status = sp.status || (act != null ? '90일 실거래' : lng != null ? '180일 실거래' : '비교자료 부족');
  const is180 = (status === '장기 실측 참고치' || status === '180일 실거래' || (sp.longTerm180d?.percent != null && act == null));
  const isInsufficient = (status === '데이터 부족' || status === '비교자료 부족' || (act == null && lng == null));

  const badgeCls = (!is180 && !isInsufficient) ? 'badge-actual' : (is180 ? 'badge-long' : 'badge-muted');
  const badgeLabel = (!is180 && !isInsufficient) ? '90일 실거래' : (is180 ? '180일 실거래' : '비교자료 부족');

  const totalObsListings = r.coverage?.listings ?? (r.askingSeries?.[0]?.matched ?? 0);
  const totalObsComps = r.coverage?.success ?? (r.coverage?.roster ?? 0);

  let matchedListings = 0;
  let groupsCount = 0;
  let lagDays = null;

  if (isInsufficient) {
    matchedListings = 0;
    groupsCount = 0;
    lagDays = null;
  } else if (is180) {
    matchedListings = sp.longTerm180d?.matchedListings ?? sp.longTerm180d?.sample ?? 0;
    groupsCount = sp.longTerm180d?.groups ?? (sp.longTerm180d?.sample ?? 0);
    lagDays = sp.longTerm180d?.medianBenchmarkAgeDays ?? null;
  } else {
    matchedListings = sp.actual90d?.matchedListings ?? sp.actual90d?.sample ?? (status === '실측' ? sp.sample : 0) ?? 0;
    groupsCount = sp.actual90d?.groups ?? (status === '실측' ? sp.groups : 0) ?? (matchedListings > 0 ? matchedListings : 0);
    lagDays = sp.medianBenchmarkAgeDays ?? null;
  }

  let noteHtml = '';
  if (isInsufficient || displayVal == null) {
    noteHtml = `<div class="detail-note warn"><b>안내:</b> 최근 12개월 내 비교 가능한 동일 단지·전용면적·층 구간의 국토부 실거래가 부족하여 가격괴리지수 산출을 유보했습니다.</div>`;
  } else if (is180) {
    noteHtml = `<div class="detail-note"><b>안내:</b> 최근 90일 내 거래가 부족하여 180일 장기 실측치(시차 약 ${lagDays != null ? lagDays.toFixed(0) : '30'}일 전)를 적용한 참고치입니다.</div>`;
  } else if (groupsCount <= 1) {
    noteHtml = `<div class="detail-note warn"><b>주의:</b> 비교 그룹이 1개뿐인 표본으로, 이 수치가 ${name} 전체 아파트의 일반적인 호가 수준을 대변하지는 않습니다.</div>`;
  } else {
    noteHtml = `<div class="detail-note"><b>검증:</b> 동일 평형·층 구간 실거래 3건 이상 요건을 충족한 ${groupsCount}개 비교 그룹의 실측 중위값입니다.</div>`;
  }

  // Concession info
  const c1 = r.concessions?.['1'] || {}, c7 = r.concessions?.['7'] || {};
  const cc = (c1.sample >= 10 && c1.cutShare != null) ? c1 : ((c7.sample >= 10 && c7.cutShare != null) ? c7 : null);
  let adjText = '2회차 관측 대기';
  if (cc && cc.cutShare != null) {
    const net = (cc.riseShare || 0) - (cc.cutShare || 0);
    adjText = `${signed(net, '%p')} (인하 ${cc.cutShare.toFixed(1)}% · 인상 ${(cc.riseShare || 0).toFixed(1)}%)`;
  }

  // Vitality info
  const ab = r.absorption, prov = r.provisionalAbsorption;
  let vitText = '30일 패널 구축 중';
  if (ab && ab.percent != null) {
    vitText = `100건당 ${ab.percent.toFixed(1)}건`;
  } else if (prov && prov.percent != null) {
    vitText = `100건당 ${prov.percent.toFixed(1)}건 (잠정)`;
  }

  const asof = fmtDate(data.asking?.lastSuccess || data.market.day);
  const dateSuffix = state.selectedDate ? ` (${state.selectedDate})` : '';

  card.innerHTML = `
    <div class="detail-head">
      <h3>${name} <span class="badge ${badgeCls}">${badgeLabel}</span></h3>
      <span style="font-size:11px;color:var(--ink-3)">코드 ${c}</span>
    </div>
    <div class="detail-main">
      <div class="detail-val ${displayVal != null ? dirClass(displayVal) : 'na'}">
        ${displayVal != null ? signed(displayVal) : '산출 유보'}
      </div>
      <div class="detail-sub">
        ${displayVal != null ? `호가가 실거래 기준가격보다 ${displayVal > 0 ? signed(displayVal) + ' 높음' : Math.abs(displayVal).toFixed(1) + '% 낮음'}` : '비교 실거래 표본 부족'}
      </div>
    </div>
    <div class="detail-grid">
      <div class="detail-cell">
        <span class="detail-cell-l">총 관측 호가</span>
        <span class="detail-cell-v">${totalObsComps}단지 ${nf(totalObsListings)}건</span>
      </div>
      <div class="detail-cell">
        <span class="detail-cell-l">지수 산출 실측 매칭</span>
        <span class="detail-cell-v">${nf(matchedListings)}건 <span style="font-size:12px;font-weight:400;color:var(--ink-3)">(${groupsCount}개 그룹)</span></span>
      </div>
      <div class="detail-cell">
        <span class="detail-cell-l">기준 실거래 시차</span>
        <span class="detail-cell-v small">${lagDays != null ? `평균 ${lagDays.toFixed(1)}일 전` : (isInsufficient ? '자료 부족' : '90일 이내')}</span>
      </div>
      <div class="detail-cell">
        <span class="detail-cell-l">호가조정 (인하·인상)</span>
        <span class="detail-cell-v small">${adjText}</span>
      </div>
      <div class="detail-cell">
        <span class="detail-cell-l">거래활력</span>
        <span class="detail-cell-v small">${vitText}</span>
      </div>
      <div class="detail-cell">
        <span class="detail-cell-l">데이터 기준일</span>
        <span class="detail-cell-v small">${asof}${dateSuffix}</span>
      </div>
    </div>
    ${noteHtml}
    <div class="detail-foot">
      <span>출처: 국토교통부 실거래가 · 네이버 매물</span>
      <button type="button" style="font-size:11px;padding:3px 8px;min-height:26px" onclick="selectDistrict('${c}', true)">표에서 보기</button>
    </div>
  `;
}

/* ---------- 카드·표 ---------- */
function setTile(id, value, wip) { const el = get(id); el.textContent = value; el.className = 'v' + (wip ? ' wip' : ''); }
function setRef(id, text) { const el = get(id); el.hidden = !text; el.textContent = text || ''; }

function renderNegoHero() {
  const hero = get('section-nego-hero');
  if (!hero || !data) return;
  const n = data.negoIndex || {};
  const gA = n.gradeA || {};
  const gB = n.gradeB_Exploratory || {};
  const asof = gA.asOf || fmtDate(data.asking?.lastSuccess) || fmtDate(data.market?.day);

  const badgeEl = get('negoStatusBadge');
  if (badgeEl) badgeEl.textContent = n.statusLabel || '개발 중 · 개별 매물-실거래 연결 검증 단계';

  const asofEl = get('negoAsof');
  if (asofEl) asofEl.textContent = asof;

  const sampleEl = get('negoSampleCount');
  if (sampleEl) sampleEl.textContent = `${gA.sample ?? 0}건 (A등급 확정 검증 중)`;

  const curValEl = get('negoCurrentVal');
  if (curValEl) {
    if (gA.currentNegoPct != null) {
      curValEl.textContent = `${signed(gA.currentNegoPct)}%`;
      curValEl.className = dirClass(gA.currentNegoPct);
    } else {
      curValEl.textContent = '검증 중';
      curValEl.className = 'na';
    }
  }

  const wowEl = get('negoWowChange');
  if (wowEl) {
    if (gA.wowChangePctPoint != null) {
      wowEl.textContent = `${signed(gA.wowChangePctPoint)}%p`;
      wowEl.className = dirClass(gA.wowChangePctPoint);
    } else {
      wowEl.textContent = '산출 대기';
      wowEl.className = 'na';
    }
  }

  const momEl = get('negoMomChange');
  if (momEl) {
    if (gA.momChangePctPoint != null) {
      momEl.textContent = `${signed(gA.momChangePctPoint)}%p`;
      momEl.className = dirClass(gA.momChangePctPoint);
    } else {
      momEl.textContent = '산출 대기';
      momEl.className = 'na';
    }
  }

  const bExpEl = get('negoBExploratory');
  if (bExpEl) {
    if (gB.medianClosingNegoPct != null) {
      bExpEl.textContent = `중위 ${gB.medianClosingNegoPct.toFixed(1)}%`;
      bExpEl.className = '';
    } else {
      bExpEl.textContent = '분석 중';
      bExpEl.className = 'na';
    }
  }
}

function renderObservabilityBar() {
  const bar = get('observabilityBar');
  if (!bar || !data) return;
  const o = data.observability || {};
  const a = data.asking || {};
  const todaySuccess = o.todayCoreSuccess ?? a.successes ?? 0;
  const todayTarget = o.todayCoreTarget ?? (todaySuccess + (o.todayCoreFailures ?? 0));
  const successRate = o.todayCoreSuccessRate != null ? `${o.todayCoreSuccessRate}%` : (a.successes != null && (a.successes + (a.failures || 0)) > 0 ? `${(a.successes / (a.successes + (a.failures || 0)) * 100).toFixed(1)}%` : '미확인');
  const coreTotal = o.coreSampleCount ?? 375;
  const coreCovRate = o.coreCoverageRate != null ? `${o.coreCoverageRate}%` : (todaySuccess > 0 ? `${(todaySuccess / coreTotal * 100).toFixed(1)}%` : '미확인');
  const obs7d = o.observed7d ?? todaySuccess;
  const obs30d = o.observed30d ?? todaySuccess;
  const activeListings = o.activeListings ?? a.listings ?? 0;
  const asOf = o.asOf || fmtDate(a.lastSuccess) || fmtDate(data.market?.day);

  bar.innerHTML = `
    <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
      <span><b style="color:var(--ink)">오늘 관측 표본:</b> ${nf(todaySuccess)}개 단지 <span style="color:var(--up);font-weight:600">(작업 성공률 ${successRate})</span></span>
      <span><b style="color:var(--ink)">핵심 표본 커버리지:</b> ${nf(todaySuccess)}/${coreTotal}개 <span style="color:var(--ink-2);font-weight:600">(${coreCovRate})</span></span>
      <span><b style="color:var(--ink)">최근 7일:</b> ${nf(obs7d)}개 단지</span>
      <span><b style="color:var(--ink)">최근 30일:</b> ${nf(obs30d)}개 단지</span>
      <span><b style="color:var(--ink)">실제 관측 매물:</b> ${nf(activeListings)}건</span>
    </div>
    <div style="display:flex;align-items:center;gap:12px;font-size:11px;color:var(--muted)">
      <span>고정 표본(375개) · 순환 풀(5,446개) 분리 운영</span>
      <span>마지막 정상 갱신: ${asOf}</span>
    </div>
  `;
}

function renderMarket() {
  renderNegoHero();
  renderObservabilityBar();
  const all = data.market.regions.all;
  const a = data.asking || {};
  const asof = a.lastSuccess ? fmtDate(a.lastSuccess) : fmtDate(data.market.day);
  const days = (all.askingSeries || []).length;
  
  // Exclude 'all' from district counting!
  const districtEntries = Object.entries(data.market.regions).filter(([c]) => c !== 'all');
  const actualDistricts = districtEntries.filter(([c]) => {
    const sp = getRegionData(c).spread || {};
    return sp.status === '실측' || (sp.actual90d?.percent != null);
  }).length;
  const longDistricts = districtEntries.filter(([c]) => {
    const sp = getRegionData(c).spread || {};
    return sp.status === '장기 실측 참고치' || (sp.status !== '실측' && sp.longTerm180d?.percent != null);
  }).length;
  const insuffDistricts = districtEntries.length - actualDistricts - longDistricts;
  const obsSpreadCount = actualDistricts + longDistricts;

  get('marketState').textContent = data.market.state || '';

  /* 가격괴리지수: 대표지수 공표 전에는 참고치를 작은 보조 줄로만 */
  const allSpread = getAllSpread();
  setTile('premium', '데이터 축적 중', true);
  setRef('premiumRef', allSpread != null
    ? `참고 괴리율 ${signed(allSpread)} · 90일 실거래 ${actualDistricts}개 구 · 180일 실거래 ${longDistricts}개 구 (대표지수 아님)` : '');
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

  /* 03 지역 표 헤더 집계: 정확한 동적 산출 */
  get('regionQ').textContent = `호가 관측 ${districtEntries.length}개 구 (${nf(a.successes || 0)}개 단지) · 가격괴리 관측 ${obsSpreadCount}개 구 (90일 실거래 ${actualDistricts} · 180일 실거래 ${longDistricts} · 비교자료 부족 ${insuffDistricts})`;

  const rank = get('ranking').value;
  const rows = Object.entries(data.districts).map(([c, name]) => {
    const r = getRegionData(c);
    const sp = r.spread || {};
    const act = sp.actual90d?.percent ?? sp.percent ?? null;
    const lng = sp.longTerm180d?.percent ?? null;
    const mdl = sp.modelEst?.percent ?? null;
    const status = sp.status || (act != null ? '90일 실거래' : lng != null ? '180일 실거래' : mdl != null ? '모형 추정' : '비교자료 부족');
    const displayVal = act != null ? act : lng != null ? lng : mdl != null ? mdl : null;
    const listingsCount = r.coverage?.listings ?? (r.askingSeries?.[0]?.matched ?? 0);
    const compsCount = r.coverage?.success ?? (r.coverage?.roster ?? 0);
    
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
    tr.dataset.code = row.code;
    if (mapState.selectedCode === row.code) tr.className = 'row-selected';

    tr.addEventListener('click', () => {
      selectDistrict(row.code, false);
    });

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

  // Render Map, Summary & Detail Card
  renderSeoulMap();
  renderMapSummary();
  renderDistrictDetail(mapState.selectedCode);
}

/* ---------- 날짜 선택 및 뷰 갱신 ---------- */
function initDateSelect() {
  const selList = [get('obsDateSelect'), get('mapDateSelect')].filter(Boolean);
  if (!selList.length || !data) return;

  const snaps = data.market.dailySnapshots || {};
  const dates = Array.from(new Set([
    ...Object.keys(snaps),
    data.market.day,
    ...(data.market.regions.all?.askingSeries || []).map(p => p.day)
  ].filter(Boolean))).sort();

  selList.forEach(sel => {
    sel.replaceChildren(...dates.map(d => {
      const opt = document.createElement('option');
      opt.value = d;
      const isLatest = d === data.market.day;
      opt.textContent = `${d}${isLatest ? ' (최신 관측일)' : ''}`;
      return opt;
    }));
  });

  if (dates.length) {
    if (!state.selectedDate || !dates.includes(state.selectedDate)) {
      state.selectedDate = dates.at(-1);
    }
    selList.forEach(sel => sel.value = state.selectedDate);
  }

  selList.forEach(sel => {
    sel.addEventListener('change', e => {
      state.selectedDate = e.target.value;
      selList.forEach(s => { if (s !== sel) s.value = state.selectedDate; });
      updateDateView();
    });
  });
}

function updateDateView() {
  renderSeoulMap();
  renderMapSummary();
  renderDistrictDetail(mapState.selectedCode);
  renderMarket();
  charts.forEach(ch => { ch.reset(); ch.draw(); });
}

/* ---------- 컨트롤 ---------- */
function bindSeg(id, attr, onPick) {
  const el = get(id);
  if (!el) return;
  el.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    el.querySelectorAll('button').forEach(x => {
      x.classList.toggle('seg-on', x === b);
      x.setAttribute('aria-pressed', String(x === b));
      x.setAttribute('aria-selected', String(x === b));
    });
    onPick(b.dataset[attr]);
  });
}

bindSeg('metricSeg', 'metric', v => { state.metric = v; chart1.reset(); chart1.draw(); });
bindSeg('rangeSeg', 'range', v => { state.range = Number(v); chart1.draw(); });
bindSeg('mapModeSeg', 'mode', v => {
  mapState.mode = v;
  renderSeoulMap();
  renderDistrictDetail(mapState.selectedCode);
});

get('district').onchange = () => {
  selectDistrict(get('district').value, true);
};
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
  renderSeoulMap();
};
mq.addEventListener?.('change', () => {
  charts.forEach(c => c.draw());
  renderSeoulMap();
});

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
  initDateSelect();
  renderMarket();
  get('coverage').textContent = `${nf(data.districtMonths)}개 구·월 · 원자료 ${nf(data.raw)}건 · 분석 대상 ${nf(data.eligibleTrades)}건 · ${data.version}`;
  get('chartNote').textContent = '점선은 잠정 구간(신고 시차 미반영), 끊긴 선은 자료가 없는 기간입니다. 지수는 기준 시점 = 100.';
  charts.forEach(c => c.draw());
}).catch(() => { get('meta').textContent = '자료를 불러오지 못했습니다.'; });
