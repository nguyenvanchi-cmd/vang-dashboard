/* Vàng hôm nay — mã giao diện. Không dùng thư viện ngoài trừ TradingView Lightweight Charts. */
(() => {
  'use strict';

  // ------------------------------------------------------------ tiện ích
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const NF = {};
  const nf = (d) => (NF[d] ||= new Intl.NumberFormat('vi-VN', { minimumFractionDigits: d, maximumFractionDigits: d }));
  const ok = (x) => x !== null && x !== undefined && !Number.isNaN(Number(x));
  const fmt = (x, d = 2) => (ok(x) ? nf(d).format(Number(x)) : '—');
  const pct = (x, d = 2) => (ok(x) ? (Number(x) > 0 ? '+' : '') + fmt(x, d) + '%' : '—');
  const sgn = (x, d = 2) => (ok(x) ? (Number(x) > 0 ? '+' : '') + fmt(x, d) : '—');
  const cls = (x) => (!ok(x) ? '' : Number(x) > 0 ? 'up' : Number(x) < 0 ? 'down' : 'flat');
  const dmy = (s) => (s && s.length >= 10 ? `${s.slice(8, 10)}/${s.slice(5, 7)}/${s.slice(0, 4)}` : '—');
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const dirClass = (s) => {
    const t = String(s || '').toLowerCase();
    if (/^(tăng|lên|tích cực)/.test(t)) return 'up';
    if (/^(giảm|xuống|tiêu cực)/.test(t)) return 'down';
    return 'flat';
  };
  const isDark = () => document.documentElement.getAttribute('data-theme') !== 'light';

  const state = { d: {}, charts: {}, inited: {}, hist: { page: 0, rows: [] }, season: 'y10' };

  async function load(name) {
    const v = Math.floor(Date.now() / 600000);
    const res = await fetch(`data/${name}?v=${v}`, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`${name}: ${res.status}`);
    return res.json();
  }

  function toast(msg) {
    const t = $('#toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => t.classList.remove('show'), 2200);
  }

  // ------------------------------------------------------------ chỉ báo
  function ema(vals, n) {
    const k = 2 / (n + 1);
    const out = new Array(vals.length);
    let e = vals[0];
    for (let i = 0; i < vals.length; i++) {
      e = i === 0 ? vals[0] : vals[i] * k + e * (1 - k);
      out[i] = e;
    }
    return out;
  }
  function rsi(vals, n = 14) {
    const out = new Array(vals.length).fill(null);
    let up = 0, dn = 0;
    for (let i = 1; i < vals.length; i++) {
      const d = vals[i] - vals[i - 1];
      const u = Math.max(d, 0), w = Math.max(-d, 0);
      if (i === 1) { up = u; dn = w; } else { up += (u - up) / n; dn += (w - dn) / n; }
      out[i] = dn === 0 ? 100 : 100 - 100 / (1 + up / dn);
    }
    return out;
  }
  function series(prices) {
    const rows = prices.rows;
    const t = rows.map((r) => r[0]);
    const o = rows.map((r) => r[1]), h = rows.map((r) => r[2]), l = rows.map((r) => r[3]), c = rows.map((r) => r[4]);
    const e12 = ema(c, 12), e26 = ema(c, 26);
    const macd = c.map((_, i) => e12[i] - e26[i]);
    const sig = ema(macd, 9);
    return {
      t, o, h, l, c,
      ema20: ema(c, 20), ema50: ema(c, 50), ema200: ema(c, 200),
      rsi: rsi(c), macd, sig, hist: macd.map((m, i) => m - sig[i]),
      chg: c.map((v, i) => (i ? (v / c[i - 1] - 1) * 100 : null)),
    };
  }

  // ------------------------------------------------------------ biểu đồ
  let chartsReady = null;
  function ensureCharts() {
    if (window.LightweightCharts) return Promise.resolve(true);
    if (chartsReady) return chartsReady;
    chartsReady = new Promise((resolve) => {
      const s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js';
      s.onload = () => resolve(!!window.LightweightCharts);
      s.onerror = () => resolve(false);
      document.head.appendChild(s);
    });
    return chartsReady;
  }
  const gridColor = () => (isDark() ? 'rgba(255,255,255,0.05)' : 'rgba(15,23,42,0.06)');
  function chartOpts(extra = {}) {
    return Object.assign({
      autoSize: true,
      layout: { background: { type: 'solid', color: 'transparent' }, textColor: css('--muted'), fontSize: 12,
        fontFamily: 'Inter, "Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif' },
      grid: { vertLines: { color: gridColor() }, horzLines: { color: gridColor() } },
      rightPriceScale: { borderColor: css('--border') },
      timeScale: { borderColor: css('--border'), rightOffset: 3 },
      crosshair: { mode: 0 },
      localization: { locale: 'vi-VN', dateFormat: 'dd/MM/yyyy', priceFormatter: (p) => fmt(p, 2) },
    }, extra);
  }
  function makeChart(el, extra) {
    const ch = LightweightCharts.createChart(el, chartOpts(extra));
    (state.charts.list ||= []).push(ch);
    return ch;
  }
  function chartFail(el, msg) {
    el.innerHTML = `<div class="chart-empty">${esc(msg)}</div>`;
  }
  function rethemeCharts() {
    (state.charts.list || []).forEach((ch) => ch.applyOptions({
      layout: { textColor: css('--muted') },
      grid: { vertLines: { color: gridColor() }, horzLines: { color: gridColor() } },
      rightPriceScale: { borderColor: css('--border') }, timeScale: { borderColor: css('--border') },
    }));
    if (state.charts.candles) state.charts.candles.applyOptions(candleColors());
  }
  const candleColors = () => ({ upColor: css('--up'), downColor: css('--down'), wickUpColor: css('--up'), wickDownColor: css('--down'), borderVisible: false });
  let syncing = false;
  function syncCharts(a, b) {
    const link = (x, y) => x.timeScale().subscribeVisibleLogicalRangeChange((r) => {
      if (syncing || !r) return;
      syncing = true; y.timeScale().setVisibleLogicalRange(r); syncing = false;
    });
    link(a, b); link(b, a);
  }

  // ------------------------------------------------------------ thanh ngang
  function bars(el, items, opts = {}) {
    const max = opts.max ?? Math.max(1e-9, ...items.map((x) => Math.abs(x.value || 0)));
    el.innerHTML = items.map((x) => {
      const v = Number(x.value || 0);
      let bar;
      if (opts.centered) {
        const w = Math.min(50, (Math.abs(v) / max) * 50);
        bar = `<span class="zero"></span><i class="${v >= 0 ? 'pos' : 'neg'}" style="${v >= 0 ? `left:50%;width:${w}%` : `left:${50 - w}%;width:${w}%`}"></i>`;
      } else {
        bar = `<i class="${opts.color || 'gold'}" style="left:0;width:${Math.min(100, (Math.abs(v) / max) * 100)}%"></i>`;
      }
      return `<div class="bar-row" title="${esc(x.title || '')}"><span class="lbl">${esc(x.label)}</span>
        <span class="bar-track">${bar}</span><span class="val ${opts.centered ? cls(v) : ''}">${esc(x.text ?? fmt(v))}</span></div>
        ${x.sub ? `<div class="bar-sub" style="margin:-4px 0 2px calc(min(140px, 30%) + 10px)">${esc(x.sub)}</div>` : ''}`;
    }).join('');
  }

  function sparkline(el, vals) {
    if (!vals.length) return;
    const w = 600, h = Math.max(74, Math.round(el.clientHeight || 74)), min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
    const pts = vals.map((v, i) => [(i / (vals.length - 1)) * w, h - 4 - ((v - min) / span) * (h - 8)]);
    const d = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join('');
    const color = vals[vals.length - 1] >= vals[0] ? css('--up') : css('--down');
    el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><defs><linearGradient id="sg" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0" stop-color="${color}" stop-opacity=".28"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
      <path d="${d}L${w},${h}L0,${h}Z" fill="url(#sg)"/><path d="${d}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>`;
  }

  // ------------------------------------------------------------ TỔNG QUAN
  function renderHeader() {
    const m = state.d.meta || {};
    const built = m.built_at ? new Date(m.built_at) : null;
    if (built && !Number.isNaN(built.getTime())) {
      const s = built.toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'Asia/Ho_Chi_Minh' });
      $('#updated-txt').textContent = `Cập nhật ${s}`;
      const stale = Date.now() - built.getTime() > 2.5 * 86400000;
      $('#updated-dot').classList.toggle('stale', stale);
      $('#build-info').textContent = `Dữ liệu giá đến ${dmy(m.last_date)} · ${fmt(m.rows, 0)} phiên.`;
    }
    if (m.ok === false) {
      $('#global-notice').innerHTML = `<div class="notice warn">${esc(m.error || 'Chưa có dữ liệu.')} Trang sẽ tự cập nhật sau lần chạy kế tiếp.</div>`;
    }
  }

  function renderHero() {
    const s = state.d.summary;
    if (!s) return;
    $('#h-date').textContent = dmy(s.date);
    $('#h-close').innerHTML = `${fmt(s.close, 2)}<small>USD/oz</small>`;
    $('#h-chg').innerHTML = `<span class="pill ${cls(s.chg1d)}">${sgn(s.chg1d_abs, 2)} · ${pct(s.chg1d)}</span>
      <span class="pill">${esc(s.regime)}</span><span class="pill">Cao ${fmt(s.high, 2)} · Thấp ${fmt(s.low, 2)}</span>`;
    const per = [['1 tuần', s.chg1w], ['1 tháng', s.chg1m], ['Từ đầu năm', s.ytd], ['1 năm', s.chg1y]];
    $('#h-periods').innerHTML = per.map(([k, v]) => `<div><span>${k}</span><b class="${cls(v)}">${pct(v, 1)}</b></div>`).join('');
    if (state.s) sparkline($('#h-spark'), state.s.c.slice(-120));
  }

  function renderClaude() {
    const c = state.d.claude || {};
    const s = state.d.summary || {};
    if (c && c.xu_huong) {
      $('#c-date').textContent = c.cap_nhat || dmy(c.ngay);
      const b = $('#c-trend');
      b.textContent = String(c.xu_huong).toUpperCase();
      b.className = `trend-badge ${dirClass(c.xu_huong)}`;
      b.classList.add(dirClass(c.xu_huong));
      $('#c-conf').textContent = `Mức tin cậy: ${c.tin_cay || '—'}`;
      $('#c-summary').textContent = c.tom_tat || '';
      const tiers = Array.isArray(c.ba_tang) ? c.ba_tang : [];
      $('#c-tiers').innerHTML = tiers.map((t) => `<div class="tier"><b>${esc(t.tang)}</b>
        <span class="dir ${dirClass(t.huong)}">${esc(t.huong)}</span><span class="pill ${t.trang_thai === 'Chín' ? 'gold' : ''}">${esc(t.trang_thai)}</span>
        <p>${esc(t.ly_do)}</p></div>`).join('');
    } else {
      $('#c-date').textContent = dmy(s.date);
      const b = $('#c-trend');
      b.textContent = (s.regime || '—').toUpperCase();
      b.className = `trend-badge ${s.regime === 'Xu hướng tăng' ? 'up' : s.regime === 'Xu hướng giảm' ? 'down' : 'flat'}`;
      $('#c-conf').textContent = 'Theo khung ngày';
      $('#c-summary').textContent = 'Chưa có nhận định của Claude cho hôm nay. Trạng thái trên được tính tự động từ giá đóng cửa và các đường EMA.';
    }
  }

  function kpi(label, value, note, extra = '') {
    return `<div class="kpi"><div class="label">${label}</div><div class="value">${value}</div>${note ? `<div class="note">${note}</div>` : ''}${extra}</div>`;
  }

  function renderKpis() {
    const s = state.d.summary || {};
    const dom = state.d.domestic || {};
    const ml = state.d.ml || {};
    const p = dom.premium;
    const out = [];
    if (p) {
      out.push(kpi('Vàng miếng SJC, bán ra', `${fmt(p.sjc_sell, 1)}<small>tr/lượng</small>`, `Mua vào ${fmt(p.sjc_buy, 1)}`));
      out.push(kpi('SJC cao hơn thế giới', `<span class="${p.prem_sell > 15 ? 'down' : ''}">${fmt(p.prem_sell, 1)}</span><small>tr/lượng</small>`, `Thế giới quy đổi ${fmt(p.world_vnd, 1)}`));
    }
    out.push(kpi('RSI(14) khung ngày', `<span class="${s.rsi14 < 30 ? 'down' : s.rsi14 > 70 ? 'up' : ''}">${fmt(s.rsi14, 1)}</span>`, esc(s.rsi_zone || ''),
      `<div class="meter"><i style="width:${Math.max(0, Math.min(100, s.rsi14 || 0))}%"></i></div>`));
    out.push(kpi('Cách EMA200', `<span class="${cls(s.dist_ema200)}">${pct(s.dist_ema200, 1)}</span>`, `EMA200 ở ${fmt(s.ema200, 0)}`));
    out.push(kpi('Cách đỉnh lịch sử', `<span class="down">${pct(s.dd_from_ath, 1)}</span>`, `Đỉnh ${fmt(s.ath, 0)} ngày ${dmy(s.ath_date)}`));
    out.push(kpi('Biến động 20 phiên', `${fmt(s.vol20, 1)}<small>%/năm</small>`, `Biên độ ngày trung bình ${fmt(s.atr14, 0)} USD`));
    if (ml.now) {
      const best = (ml.models || {})[ml.best] || {};
      out.push(kpi('Học máy: khả năng tăng sau 5 phiên', `${fmt(ml.now.p_up, 0)}<small>%</small>`,
        `Độ chính xác lịch sử ${fmt(best.accuracy, 1)}% (cách đơn giản ${fmt(ml.baseline_acc, 1)}%)`,
        `<div class="meter"><span class="mid"></span><i style="width:${Math.max(0, Math.min(100, ml.now.p_up))}%"></i></div>`));
    }
    $('#kpis').innerHTML = out.join('');
  }

  function renderTechState() {
    const s = state.d.summary || {};
    $('#tech-date').textContent = dmy(s.date);
    const pos = (v) => (s.close > v ? `<span class="up">Trên · ${pct((s.close / v - 1) * 100, 1)}</span>` : `<span class="down">Dưới · ${pct((s.close / v - 1) * 100, 1)}</span>`);
    const rows = [
      ['Giá so với EMA20', pos(s.ema20)],
      ['Giá so với EMA50', pos(s.ema50)],
      ['Giá so với EMA200', pos(s.ema200)],
      ['MACD', s.macd > s.macd_sig ? `<span class="up">Trên đường trung bình · ${sgn(s.macd_hist, 1)}</span>` : `<span class="down">Dưới đường trung bình · ${sgn(s.macd_hist, 1)}</span>`],
      ['RSI(14)', `${fmt(s.rsi14, 1)} · ${esc(s.rsi_zone)}`],
      ['Chuỗi phiên giảm liên tiếp', s.down_streak ? `${s.down_streak} phiên` : 'Không'],
      ['Đỉnh và đáy 52 tuần', `${fmt(s.hi52, 0)} · ${fmt(s.lo52, 0)}`],
      ['Trạng thái chung', `<span class="${s.regime === 'Xu hướng tăng' ? 'up' : s.regime === 'Xu hướng giảm' ? 'down' : 'flat'}">${esc(s.regime)}</span>`],
    ];
    $('#tech-state').innerHTML = rows.map(([k, v]) => `<div class="state-row"><span>${k}</span><span>${v}</span></div>`).join('');
  }

  function renderActivePatterns() {
    const q = state.d.quant;
    const el = $('#active-patterns');
    if (!q) { el.innerHTML = '<div class="notice">Chưa có dữ liệu định lượng.</div>'; return; }
    const base = q.events.baseline['20'];
    const act = q.events.rows.filter((r) => r.active && r.stats['20']);
    if (!act.length) { el.innerHTML = '<div class="notice">Hôm nay không có điều kiện đặc biệt nào trong danh sách theo dõi.</div>'; return; }
    el.innerHTML = act.map((r) => {
      const st = r.stats['20'];
      const diff = st.mean - base.mean;
      return `<div class="pattern"><div class="insight-head"><b>${esc(r.label)}</b><span class="pill ${cls(diff)}">${diff >= 0 ? 'Tốt hơn' : 'Kém hơn'} bình thường</span></div>
        <p>${fmt(st.n, 0)} lần trong lịch sử: 20 phiên sau thay đổi trung bình <b class="${cls(st.mean)}">${pct(st.mean)}</b>, tỷ lệ tăng ${fmt(st.hit, 0)}%. Mức bình thường: ${pct(base.mean)}, tỷ lệ tăng ${fmt(base.hit, 0)}%.</p></div>`;
    }).join('');
  }

  function renderMtf() {
    const c = state.d.claude || {};
    const rows = Array.isArray(c.da_khung) ? c.da_khung.slice().sort((a, b) => (a.thu_tu || 0) - (b.thu_tu || 0)) : [];
    if (!rows.length) { $('#mtf-card').hidden = true; return; }
    $('#mtf-body').innerHTML = rows.map((r) => `<tr class="${r.khung === '15m' ? 'hl' : ''}"><td><b>${esc(r.khung)}</b></td>
      <td class="${dirClass(r.xu_huong)}">${esc(r.xu_huong)}</td><td>${esc(r.gia_vs_ema)}</td><td class="num">${fmt(r.ema, 1)}</td>
      <td class="num ${cls(r.macd)}">${fmt(r.macd, 1)}<span class="cell-sub">${esc(r.macd_mo_ta)}</span></td>
      <td>${esc(r.ho_tro)}</td><td>${esc(r.khang_cu)}</td><td>${esc(r.ghi_chu)}</td></tr>`).join('');
  }

  function renderCalendarNews() {
    const c = state.d.claude || {};
    const cal = Array.isArray(c.lich_tin) ? c.lich_tin.slice().sort((a, b) => String(a.ngay).localeCompare(String(b.ngay))) : [];
    $('#calendar').innerHTML = cal.length ? cal.map((x) => `<div class="list-item cal-item"><span class="when">${esc(x.thu)} · ${esc(x.gio_vn)}</span>
      <span>${esc(x.su_kien)}${x.ghi_chu ? `<span class="cell-sub">${esc(x.ghi_chu)}</span>` : ''}</span>
      <span class="stars" title="Mức độ ảnh hưởng">${'★'.repeat(Math.max(0, Math.min(3, Number(x.muc_do) || 0)))}</span></div>`).join('')
      : '<div class="notice">Chưa có lịch tin.</div>';
    const news = Array.isArray(c.tin_chon_loc) ? c.tin_chon_loc.slice().sort((a, b) => (a.thu_tu || 0) - (b.thu_tu || 0)) : [];
    $('#news').innerHTML = news.length ? news.map((n) => `<div class="list-item"><span>${esc(n.tieu_de)}</span>
      <span class="meta"><span class="pill">${esc(n.tang)}</span><span class="pill ${n.trang_thai === 'Chín' ? 'gold' : ''}">${esc(n.trang_thai)}</span>
      <span class="pill ${dirClass(n.tac_dong)}">${esc(n.tac_dong)}</span>
      ${/^https:\/\//.test(n.url || '') ? `<a href="${esc(n.url)}" target="_blank" rel="noopener noreferrer">${esc(n.nguon || 'Nguồn')}</a>` : esc(n.nguon || '')}</span></div>`).join('')
      : '<div class="notice">Chưa có tin chọn lọc.</div>';
  }

  // ------------------------------------------------------------ BIỂU ĐỒ & LỊCH SỬ
  async function initPriceChart() {
    const el = $('#price-chart'), ind = $('#ind-chart');
    if (!state.s) { chartFail(el, 'Chưa có dữ liệu giá.'); return; }
    if (!(await ensureCharts())) { chartFail(el, 'Không tải được thư viện biểu đồ. Hãy tải lại trang.'); ind.hidden = true; return; }
    const S = state.s;
    const main = makeChart(el, { rightPriceScale: { borderColor: css('--border'), scaleMargins: { top: 0.08, bottom: 0.06 } } });
    const candles = main.addCandlestickSeries(candleColors());
    candles.setData(S.t.map((t, i) => ({ time: t, open: S.o[i], high: S.h[i], low: S.l[i], close: S.c[i] })));
    state.charts.candles = candles;
    const emaColors = { 20: '#60a5fa', 50: '#a78bfa', 200: '#e6b84a' };
    state.charts.ema = {};
    [20, 50, 200].forEach((n) => {
      const ser = main.addLineSeries({ color: emaColors[n], lineWidth: n === 200 ? 2 : 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      ser.setData(S.t.map((t, i) => ({ time: t, value: S[`ema${n}`][i] })));
      state.charts.ema[n] = ser;
    });
    state.charts.main = main;

    const sub = makeChart(ind, { rightPriceScale: { borderColor: css('--border'), minimumWidth: 70 }, timeScale: { visible: false, borderColor: css('--border') } });
    main.priceScale('right').applyOptions({ minimumWidth: 70 });
    state.charts.sub = sub;
    drawIndicator('rsi');
    syncCharts(main, sub);

    const idx = new Map(S.t.map((t, i) => [t, i]));
    const legend = (i) => {
      if (i == null) i = S.t.length - 1;
      $('#legend').innerHTML = `<span>${dmy(S.t[i])}</span><span>Mở <b>${fmt(S.o[i])}</b></span><span>Cao <b>${fmt(S.h[i])}</b></span>
        <span>Thấp <b>${fmt(S.l[i])}</b></span><span>Đóng <b>${fmt(S.c[i])}</b></span><span class="${cls(S.chg[i])}">${pct(S.chg[i])}</span>
        <span>EMA20 <b>${fmt(S.ema20[i], 1)}</b></span><span>EMA50 <b>${fmt(S.ema50[i], 1)}</b></span><span>EMA200 <b>${fmt(S.ema200[i], 1)}</b></span>
        <span>RSI <b>${fmt(S.rsi[i], 1)}</b></span>`;
    };
    legend();
    const timeKey = (t) => (typeof t === 'string' ? t : t && t.year ? `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}` : null);
    main.subscribeCrosshairMove((p) => legend(p && p.time ? idx.get(timeKey(p.time)) : null));
    setRange('6M');
  }

  function drawIndicator(kind) {
    const S = state.s, sub = state.charts.sub;
    if (!sub) return;
    (state.charts.indSeries || []).forEach((x) => sub.removeSeries(x));
    state.charts.indSeries = [];
    if (kind === 'rsi') {
      const line = sub.addLineSeries({ color: '#e6b84a', lineWidth: 1, priceLineVisible: false });
      line.setData(S.t.map((t, i) => (S.rsi[i] == null ? { time: t } : { time: t, value: S.rsi[i] })));
      [30, 70].forEach((lv) => line.createPriceLine({ price: lv, color: css('--faint'), lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '' }));
      state.charts.indSeries.push(line);
    } else {
      const hist = sub.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
      hist.setData(S.t.map((t, i) => ({ time: t, value: S.hist[i], color: S.hist[i] >= 0 ? 'rgba(34,197,94,0.55)' : 'rgba(240,82,82,0.55)' })));
      const m = sub.addLineSeries({ color: '#60a5fa', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
      m.setData(S.t.map((t, i) => ({ time: t, value: S.macd[i] })));
      const s2 = sub.addLineSeries({ color: '#f5a524', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
      s2.setData(S.t.map((t, i) => ({ time: t, value: S.sig[i] })));
      state.charts.indSeries.push(hist, m, s2);
    }
    if (state.charts.main) {
      const r = state.charts.main.timeScale().getVisibleLogicalRange();
      if (r) sub.timeScale().setVisibleLogicalRange(r);
    }
  }

  function setRange(key) {
    const main = state.charts.main, S = state.s;
    if (!main || !S) return;
    $$('#range-seg button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.range === key)));
    if (key === 'ALL') { main.timeScale().fitContent(); return; }
    const months = { '1M': 1, '3M': 3, '6M': 6, '1Y': 12, '3Y': 36, '5Y': 60 }[key];
    const last = new Date(S.t[S.t.length - 1] + 'T00:00:00Z');
    const from = new Date(last); from.setUTCMonth(from.getUTCMonth() - months);
    const f = from.toISOString().slice(0, 10);
    const i0 = Math.max(0, S.t.findIndex((t) => t >= f));
    main.timeScale().setVisibleLogicalRange({ from: i0, to: S.t.length - 1 + 3 });
  }

  function buildHistRows() {
    const S = state.s;
    const rows = [];
    for (let i = S.t.length - 1; i >= 0; i--) {
      rows.push({ t: S.t[i], o: S.o[i], h: S.h[i], l: S.l[i], c: S.c[i], chg: S.chg[i], rsi: S.rsi[i],
        d200: i >= 199 ? (S.c[i] / S.ema200[i] - 1) * 100 : null });
    }
    state.hist.all = rows;
  }

  function renderHist() {
    const q = $('#hist-search').value.trim();
    const f = $('#hist-filter').value;
    let rows = state.hist.all || [];
    if (q) {
      const m = q.match(/^(\d{1,2})\/(\d{1,2})(?:\/(\d{4}))?$/);
      const key = m ? `${m[3] ? m[3] + '-' : ''}${m[2].padStart(2, '0')}-${m[1].padStart(2, '0')}` : q;
      rows = rows.filter((r) => r.t.includes(key) || dmy(r.t).includes(q));
    }
    const filters = {
      drop2: (r) => r.chg != null && r.chg <= -2, rise2: (r) => r.chg != null && r.chg >= 2,
      rsi30: (r) => r.rsi != null && r.rsi < 30, rsi70: (r) => r.rsi != null && r.rsi > 70,
      below200: (r) => r.d200 != null && r.d200 < 0,
    };
    if (filters[f]) rows = rows.filter(filters[f]);
    const per = 25, pages = Math.max(1, Math.ceil(rows.length / per));
    state.hist.page = Math.min(state.hist.page, pages - 1);
    const pg = rows.slice(state.hist.page * per, state.hist.page * per + per);
    $('#hist-body').innerHTML = pg.length ? pg.map((r) => `<tr><td>${dmy(r.t)}</td><td class="num">${fmt(r.o)}</td><td class="num">${fmt(r.h)}</td>
      <td class="num">${fmt(r.l)}</td><td class="num"><b>${fmt(r.c)}</b></td><td class="num ${cls(r.chg)}">${pct(r.chg)}</td>
      <td class="num">${fmt(r.rsi, 1)}</td><td class="num ${cls(r.d200)}">${pct(r.d200, 1)}</td></tr>`).join('')
      : '<tr><td colspan="8" class="muted">Không có phiên nào khớp.</td></tr>';
    $('#pg-info').textContent = `${fmt(rows.length, 0)} phiên · trang ${state.hist.page + 1}/${pages}`;
    $('#pg-prev').disabled = state.hist.page === 0;
    $('#pg-next').disabled = state.hist.page >= pages - 1;
  }

  // ------------------------------------------------------------ ĐỊNH LƯỢNG
  function renderInsights() {
    const q = state.d.quant;
    if (!q) { $('#insights').innerHTML = '<div class="notice">Chưa có dữ liệu.</div>'; return; }
    const s = state.d.summary || {};
    $('#q-range').textContent = `${dmy(s.first_date)} – ${dmy(s.date)} · ${fmt(s.rows, 0)} phiên`;
    const tone = { 'mạnh': 'gold', 'khá': 'gold', 'vừa': '', 'yếu': 'flat' };
    $('#insights').innerHTML = q.insights.map((x) => `<div class="insight ${x.active ? 'active' : ''}"><div class="insight-head"><b>${esc(x.title)}</b>
      <span class="pill ${tone[x.strength] || ''}">Độ tin cậy: ${esc(x.strength)}</span></div><p>${esc(x.text)}</p></div>`).join('');
  }

  function renderEvents() {
    const q = state.d.quant;
    if (!q) return;
    const ev = q.events, H = ['1', '5', '20', '60'];
    const base = ev.baseline;
    const cell = (st, h) => {
      if (!st) return '<td class="num faint">—</td>';
      const diff = st.mean - base[h].mean;
      return `<td class="num"><b class="${cls(diff)}">${pct(st.mean)}</b><span class="cell-sub">tăng ${fmt(st.hit, 0)}%</span></td>`;
    };
    const baseRow = `<tr class="base"><td>Bình thường (mọi ngày)</td><td class="num">—</td>${H.map((h) => `<td class="num">${pct(base[h].mean)}<span class="cell-sub">tăng ${fmt(base[h].hit, 0)}%</span></td>`).join('')}<td></td></tr>`;
    $('#event-body').innerHTML = baseRow + ev.rows.map((r) => `<tr class="${r.active ? 'hl' : ''}"><td>${esc(r.label)}<span class="cell-sub">${r.type === 'event' ? 'Sự kiện' : 'Trạng thái'}</span></td>
      <td class="num">${fmt(r.count, 0)}</td>${H.map((h) => cell(r.stats[h], h)).join('')}<td>${r.active ? '<span class="pill gold">Đang xảy ra</span>' : ''}</td></tr>`).join('');
  }

  function renderSeason() {
    const q = state.d.quant;
    if (!q) return;
    const s = q.seasonality[state.season] || q.seasonality.all;
    bars($('#season-wd'), s.weekday.map((x) => ({ label: x.label, value: x.mean, text: pct(x.mean, 3), sub: `Tăng ${fmt(x.hit, 0)}% · ${fmt(x.n, 0)} phiên` })), { centered: true });
    bars($('#season-mo'), s.month.map((x) => ({ label: x.label, value: x.mean, text: pct(x.mean, 2), sub: `Tăng ${fmt(x.hit, 0)}% · ${fmt(x.n, 0)} năm` })), { centered: true });
    $$('.season-seg button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.s === state.season)));
  }

  const BT_COLORS = { buy_hold: '#e6b84a', ema200: '#60a5fa', ema50_200: '#a78bfa', macd: '#22c55e' };
  function renderBacktestTable() {
    const q = state.d.quant;
    if (!q) return;
    const bt = q.backtest;
    $('#bt-sub').textContent = `${dmy(bt.from)} – ${dmy(bt.to)} · 1 USD ban đầu`;
    $('#bt-body').innerHTML = bt.rows.map((r) => `<tr class="${r.key === 'buy_hold' ? 'base' : ''}"><td><span class="sw" style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${BT_COLORS[r.key]};margin-right:8px"></span>${esc(r.label)}</td>
      <td class="num ${cls(r.world.cagr)}">${pct(r.world.cagr, 1)}</td><td class="num down">${pct(r.world.maxdd, 1)}</td><td class="num">${fmt(r.world.vol, 1)}%</td>
      <td class="num">${fmt(r.world.sharpe, 2)}</td><td class="num">${fmt(r.world.exposure, 0)}%</td><td class="num ${cls(r.vn.cagr)}">${pct(r.vn.cagr, 1)}</td></tr>`).join('');
    $('#bt-note').textContent = `Phí: ${bt.costs.world}; cột cuối: ${bt.costs.vn}. Biểu đồ dùng thang log.`;
  }
  async function initBacktestChart() {
    const q = state.d.quant, el = $('#bt-chart');
    if (!q) return;
    if (!(await ensureCharts())) { chartFail(el, 'Không tải được thư viện biểu đồ.'); return; }
    const ch = makeChart(el, { rightPriceScale: { mode: 1, borderColor: css('--border') }, localization: { locale: 'vi-VN', dateFormat: 'dd/MM/yyyy', priceFormatter: (p) => fmt(p, 2) } });
    const bt = q.backtest;
    const legend = [];
    bt.rows.forEach((r) => {
      const pts = bt.curves[r.key] || [];
      const ser = ch.addLineSeries({ color: BT_COLORS[r.key], lineWidth: r.key === "buy_hold" ? 2 : 1, priceLineVisible: false, lastValueVisible: true, title: '' });
      const seen = new Set();
      ser.setData(pts.filter((p) => !seen.has(p[0]) && seen.add(p[0])).map((p) => ({ time: p[0], value: p[1] })));
      legend.push(`<span><i class="sw" style="display:inline-block;width:10px;height:3px;background:${BT_COLORS[r.key]};vertical-align:middle;margin-right:5px"></i>${esc(r.label)} <b>×${fmt(pts.length ? pts[pts.length - 1][1] : null, 2)}</b></span>`);
    });
    ch.timeScale().fitContent();
    $('#bt-legend').innerHTML = legend.join('');
  }

  function renderAccumulation() {
    const q = state.d.quant;
    if (!q || !q.accumulation || !q.accumulation.length) { $('#acc').innerHTML = '<div class="notice">Chưa đủ dữ liệu.</div>'; return; }
    $('#acc').innerHTML = q.accumulation.map((a) => `<div style="margin-bottom:14px"><div class="eyebrow" style="margin-bottom:8px">${a.years} năm gần nhất · ${fmt(a.months, 0)} tháng · ${dmy(a.from)} – ${dmy(a.to)}</div>
      <div class="table-wrap"><table><thead><tr><th>Cách mua</th><th class="num">Giá vốn bình quân</th><th class="num">Lượng vàng</th><th class="num">Tổng tiền bỏ ra</th><th class="num">Giá trị cuối kỳ</th><th class="num">Lãi/lỗ</th><th class="num">Tiền chưa dùng</th></tr></thead>
      <tbody>${a.rows.map((r, i) => `<tr class="${i === 0 ? 'base' : ''}"><td>${esc(r.label)}</td><td class="num">${fmt(r.avg_cost, 0)} USD/oz</td><td class="num">${fmt(r.oz, 2)} oz</td>
      <td class="num">${fmt(r.invested, 0)} USD</td><td class="num">${fmt(r.value, 0)} USD</td><td class="num ${cls(r.ret)}">${pct(r.ret, 1)}</td><td class="num">${fmt(r.cash_left, 0)} USD</td></tr>`).join('')}</tbody></table></div>
      <p class="small faint" style="margin-top:6px">Số tháng có Mua xác nhận: ${fmt(a.events.mua_xac_nhan, 0)} · số lần dùng quỹ chờ: ${fmt(a.events.quy_cho, 0)}.</p></div>`).join('');
  }

  function renderMl() {
    const ml = state.d.ml;
    if (!ml || !ml.now) { $('#ml-verdict').textContent = 'Chưa có kết quả mô hình.'; return; }
    const best = ml.models[ml.best];
    $('#ml-sub').textContent = `${ml.best_label} · kiểm tra ${dmy(ml.test_from)} – ${dmy(ml.test_to)}`;
    $('#ml-prob').innerHTML = `<span class="${ml.now.p_up >= 55 ? 'up' : ml.now.p_up <= 45 ? 'down' : ''}">${fmt(ml.now.p_up, 1)}%</span>`;
    $('#ml-marker').style.left = `${Math.max(0, Math.min(100, ml.now.p_up))}%`;
    const v = $('#ml-verdict');
    v.textContent = ml.verdict;
    v.classList.toggle('weak', ml.strength === 'yếu');
    const other = ml.best === 'gbm' ? 'logit' : 'gbm';
    const m = [
      ['Độ chính xác', `${fmt(best.accuracy, 1)}%`], ['Cách đoán đơn giản', `${fmt(ml.baseline_acc, 1)}%`],
      ['AUC', fmt(best.auc, 3)], ['Số phiên kiểm tra', fmt(ml.n_test, 0)],
      ['Mô hình còn lại', `${fmt(ml.models[other].accuracy, 1)}% · AUC ${fmt(ml.models[other].auc, 3)}`],
      ['Lợi nhuận/năm nếu theo mô hình', `${pct(ml.strategy.model_cagr, 1)} <span class="small muted">vs ${pct(ml.strategy.bh_cagr, 1)}</span>`],
    ];
    $('#ml-metrics').innerHTML = m.map(([k, x]) => `<div class="metric"><span>${k}</span><b>${x}</b></div>`).join('');
    bars($('#ml-years'), ml.per_year.slice(-12).map((y) => ({ label: String(y.year), value: y.acc - 50, text: `${fmt(y.acc, 1)}%`, title: `Cách đơn giản: ${fmt(y.base, 1)}%` })), { centered: true, max: 12 });
    bars($('#ml-imp'), ml.importance.slice(0, 8).map((x) => ({ label: x.feature, value: x.value, text: fmt(x.value, 3) })), { color: 'blue' });
  }

  // ------------------------------------------------------------ TRONG NƯỚC
  function renderDomestic() {
    const dom = state.d.domestic || {};
    const p = dom.premium, fx = dom.usd_vnd;
    const k = [];
    if (p) {
      k.push(kpi('SJC bán ra', `${fmt(p.sjc_sell, 1)}<small>tr/lượng</small>`, `Mua vào ${fmt(p.sjc_buy, 1)}`));
      k.push(kpi('Thế giới quy đổi', `${fmt(p.world_vnd, 1)}<small>tr/lượng</small>`, `Theo giá đóng cửa ${dmy(p.world_date)}`));
      k.push(kpi('Chênh lệch SJC – thế giới', `<span class="${p.prem_sell > 15 ? 'down' : ''}">${fmt(p.prem_sell, 1)}</span><small>tr/lượng</small>`, `Theo giá mua vào: ${fmt(p.prem_buy, 1)}`));
    }
    if (fx) k.push(kpi('Tỷ giá USD/VND, bán ra', `${fmt(fx.sell, 0)}`, `${esc(fx.source || '')} · ${dmy(fx.date)}`));
    $('#dom-kpis').innerHTML = k.join('') || '<div class="notice">Chưa có dữ liệu trong nước.</div>';
    const rows = dom.latest || [];
    $('#dom-src').textContent = dom.source || '';
    const maxBuy = {}, minBuy = {};
    rows.forEach((r) => { maxBuy[r.product] = Math.max(maxBuy[r.product] ?? -Infinity, r.buy); minBuy[r.product] = Math.min(minBuy[r.product] ?? Infinity, r.buy); });
    $('#dom-body').innerHTML = rows.length ? rows.map((r) => {
      const best = r.buy === maxBuy[r.product] && maxBuy[r.product] > minBuy[r.product];
      return `<tr class="${best ? 'hl' : ''}"><td>${esc(r.brand)}</td><td>${esc(r.product)}</td><td class="num">${fmt(r.buy, 1)}</td><td class="num">${fmt(r.sell, 1)}</td>
        <td class="num">${fmt(r.sell - r.buy, 1)}</td><td class="num">${pct((r.sell / r.buy - 1) * 100, 1)}</td><td>${esc(r.time || '')}</td></tr>`;
    }).join('') : '<tr><td colspan="7" class="muted">Chưa có dữ liệu.</td></tr>';
  }
  async function initPremChart() {
    const dom = state.d.domestic || {}, el = $('#prem-chart');
    const h = dom.history || [];
    if (h.length < 2) { chartFail(el, 'Đang tích lũy dữ liệu: biểu đồ sẽ hiện khi có từ 2 ngày giá SJC trở lên.'); return; }
    if (!(await ensureCharts())) { chartFail(el, 'Không tải được thư viện biểu đồ.'); return; }
    const ch = makeChart(el);
    const area = ch.addAreaSeries({ lineColor: '#e6b84a', topColor: 'rgba(230,184,74,0.28)', bottomColor: 'rgba(230,184,74,0.02)', lineWidth: 2, priceLineVisible: false });
    area.setData(h.map((x) => ({ time: x[0], value: x[3] })));
    ch.timeScale().fitContent();
  }

  // ------------------------------------------------------------ điều hướng
  const TAB_INIT = {
    'bieu-do': async () => { buildHistRows(); renderHist(); await initPriceChart(); },
    'dinh-luong': async () => { await initBacktestChart(); },
    'trong-nuoc': async () => { await initPremChart(); },
  };
  async function showTab(name, push = true) {
    if (!$(`#tab-${name}`)) name = 'tong-quan';
    $$('.tab').forEach((s) => s.classList.toggle('active', s.id === `tab-${name}`));
    $$('.tab-btn').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.tab === name)));
    if (push) history.replaceState(null, '', `#${name}`);
    if (TAB_INIT[name] && !state.inited[name] && state.loaded) {
      state.inited[name] = true;
      try { await TAB_INIT[name](); } catch (e) { console.error(e); }
    }
  }

  function bindUi() {
    $$('.tab-btn').forEach((b) => b.addEventListener('click', () => { showTab(b.dataset.tab); window.scrollTo({ top: 0, behavior: 'smooth' }); }));
    $('#theme-btn').addEventListener('click', () => {
      const next = isDark() ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('vang-theme', next); } catch (e) { /* bỏ qua */ }
      rethemeCharts();
      if (state.s) sparkline($('#h-spark'), state.s.c.slice(-120));
    });
    $('#share-btn').addEventListener('click', async () => {
      const url = location.href.split('#')[0];
      if (navigator.share) {
        try { await navigator.share({ title: document.title, url }); return; } catch (e) { /* người dùng hủy */ }
      }
      try { await navigator.clipboard.writeText(url); toast('Đã chép đường link trang'); } catch (e) { toast(url); }
    });
    $$('#range-seg button').forEach((b) => b.addEventListener('click', () => setRange(b.dataset.range)));
    $$('[data-ema]').forEach((c) => c.addEventListener('change', () => {
      const s = state.charts.ema && state.charts.ema[c.dataset.ema];
      if (s) s.applyOptions({ visible: c.checked });
    }));
    $('#log-scale').addEventListener('change', (e) => state.charts.main && state.charts.main.priceScale('right').applyOptions({ mode: e.target.checked ? 1 : 0 }));
    $$('#ind-seg button').forEach((b) => b.addEventListener('click', () => {
      $$('#ind-seg button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      drawIndicator(b.dataset.ind);
    }));
    let tmr;
    $('#hist-search').addEventListener('input', () => { clearTimeout(tmr); tmr = setTimeout(() => { state.hist.page = 0; renderHist(); }, 150); });
    $('#hist-filter').addEventListener('change', () => { state.hist.page = 0; renderHist(); });
    $('#pg-prev').addEventListener('click', () => { state.hist.page = Math.max(0, state.hist.page - 1); renderHist(); });
    $('#pg-next').addEventListener('click', () => { state.hist.page += 1; renderHist(); });
    $$('.season-seg button').forEach((b) => b.addEventListener('click', () => { state.season = b.dataset.s; renderSeason(); }));
  }

  async function main() {
    bindUi();
    const names = ['meta', 'summary', 'prices', 'quant', 'ml', 'domestic', 'claude'];
    const got = await Promise.allSettled(names.map((n) => load(`${n}.json`)));
    got.forEach((g, i) => { state.d[names[i]] = g.status === 'fulfilled' ? g.value : null; });
    if (state.d.prices && state.d.prices.rows && state.d.prices.rows.length) state.s = series(state.d.prices);
    const safe = (fn) => { try { fn(); } catch (e) { console.error(e); } };
    safe(renderHeader); safe(renderHero); safe(renderClaude); safe(renderKpis); safe(renderTechState);
    safe(renderActivePatterns); safe(renderMtf); safe(renderCalendarNews);
    safe(renderInsights); safe(renderEvents); safe(renderSeason); safe(renderBacktestTable); safe(renderAccumulation); safe(renderMl);
    safe(renderDomestic);
    if (!state.d.meta) {
      $('#global-notice').innerHTML = '<div class="notice warn">Chưa tải được dữ liệu. Nếu trang vừa được tạo, hãy quay lại sau ít phút.</div>';
    }
    state.loaded = true;
    const start = (location.hash || '#tong-quan').slice(1);
    await showTab(start, false);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', main);
  else main();
})();
