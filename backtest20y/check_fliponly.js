// flip-only vs monthly-rebalance 对比（动量12m Q30，回测口径）
import fs from 'fs';
const FX = 7.25;
const WINDOW = { start: '2006-08-21', end: '2026-08-20' };
function loadEM(path) { const j = JSON.parse(fs.readFileSync(path, 'utf8')); const out = {}; for (const k of j.data.klines) { const p = k.split(','); out[p[0]] = { close: +p[2] }; } return out; }
const QQQ = loadEM('qqq_em.json');
const GLD = loadEM('gld_em.json');
const days = Object.keys(QQQ).sort();
const dayIdx = new Map(days.map((d, i) => [d, i]));
function buildWeekly(start, end) {
  const bars = []; let cur = null;
  const isoWeek = (d) => { const dt = new Date(d + 'T00:00:00Z'); const day = (dt.getUTCDay() + 6) % 7; dt.setUTCDate(dt.getUTCDate() - day + 3); const firstThu = new Date(Date.UTC(dt.getUTCFullYear(), 0, 4)); const week = 1 + Math.round(((dt - firstThu) / 86400000 - 3 + ((firstThu.getUTCDay() + 6) % 7)) / 7); return dt.getUTCFullYear() + '-' + String(week).padStart(2, '0'); };
  for (const d of days) { if (d < start) continue; if (d > end) break; const wk = isoWeek(d); if (!cur) cur = { week: wk }; if (wk !== cur.week) { bars.push(cur); cur = { week: wk }; } cur.date = d; cur.qqq = QQQ[d].close; const g = GLD[d]; if (g) cur.gld = g.close; }
  if (cur && cur.qqq !== undefined) bars.push(cur);
  return bars;
}
const bars = buildWeekly(WINDOW.start, WINDOW.end);
const n = bars.length;
const init = 100000 / FX, base = 400 / FX;
const mom = (sym, i, months, skip) => { const j = i - Math.round(months * 21) - (skip ? 21 : 0); if (j < 0 || !sym[days[j]]) return 0; return sym[days[i]].close / sym[days[j]].close - 1; };
function metrics(weekly, flows, finalUSD) {
  const years = weekly.length / 52;
  let E = 1, peak = 1, maxDD = 0; const rets = [];
  for (const w of weekly) { const r = w.prevValue > 0 ? (w.value - w.prevValue - w.contrib) / w.prevValue : 0; rets.push(r); E *= (1 + r); peak = Math.max(peak, E); maxDD = Math.max(maxDD, (peak - E) / peak); }
  const var_ = rets.reduce((s, r) => s + r * r, 0) / rets.length;
  const vol = Math.sqrt(var_) * Math.sqrt(52) * 100;
  const mean = rets.reduce((s, r) => s + r, 0) / rets.length;
  const sharpe = var_ > 0 ? mean / Math.sqrt(var_) * Math.sqrt(52) : NaN;
  const cf = [{ t: 0, amt: -init }];
  for (const f of flows) cf.push({ t: f.t / 52, amt: -f.amt });
  cf.push({ t: years, amt: finalUSD });
  const npv = (r) => cf.reduce((s, c) => s + c.amt / Math.pow(1 + r, c.t), 0);
  let lo = -0.9, hi = 5; for (let k = 0; k < 300; k++) { const mid = (lo + hi) / 2; npv(mid) > 0 ? lo = mid : hi = mid; }
  const xirr = (lo + hi) / 2;
  return { xirr: xirr * 100, maxDD: maxDD * 100, vol, sharpe, calmar: maxDD > 0 ? xirr / maxDD : NaN };
}
function run(mode) {
  let qS = 0, gS = 0, cash = init, curUp = true, flips = 0;
  const weekly = [], flows = [];
  for (let i = 0; i < n; i++) {
    const b = bars[i];
    const prevValue = weekly.length ? weekly[weekly.length - 1].value : 0;
    cash += base; flows.push({ t: i, amt: base });
    const mQ = mom(QQQ, dayIdx.get(b.date), 12, true);
    const upSig = mQ > 0;
    const isME = (i === n - 1 || +bars[i + 1].date.slice(5, 7) !== +b.date.slice(5, 7));
    const qT = upSig ? 0.7 : 0.3, gT = 0.3;
    if (isME) {
      const flip = upSig !== curUp;
      if (flip) { curUp = upSig; flips++; }
      if (mode === 'monthly' || flip) {
        const st = { total: qS * b.qqq + gS * (b.gld ?? 0) + cash };
        qS = st.total * qT / b.qqq; gS = st.total * gT / (b.gld ?? 1); cash = st.total - qS * b.qqq - gS * (b.gld ?? 0);
      }
    } else {
      const buyQ = Math.min(cash * qT, cash); qS += buyQ / b.qqq; cash -= buyQ;
      const buyG = Math.min(cash * gT, cash); gS += buyG / (b.gld ?? 1); cash -= buyG;
    }
    const value = qS * b.qqq + gS * (b.gld ?? 0) + cash;
    weekly.push({ value, prevValue, contrib: base });
  }
  const finalUSD = qS * bars[n - 1].qqq + gS * (bars[n - 1].gld ?? 0) + cash;
  const m = metrics(weekly, flows, finalUSD);
  return { xirr: m.xirr, maxDD: m.maxDD, calmar: m.calmar, sharpe: m.sharpe, vol: m.vol, finalCNY: finalUSD * FX, flips };
}
const a = run('monthly'), b = run('fliponly');
console.log('动量12m Q30 | XIRR% | MaxDD% | Calmar | 夏普 | 波动% | 终值¥ | 翻转次数');
console.log(`回测版(每月调到目标) | ${a.xirr.toFixed(2)} | ${a.maxDD.toFixed(1)} | ${a.calmar.toFixed(3)} | ${a.sharpe.toFixed(2)} | ${a.vol.toFixed(1)} | ¥${Math.round(a.finalCNY / 10000)}万 | ${a.flips}`);
console.log(`简化版(只在翻转时动存量) | ${b.xirr.toFixed(2)} | ${b.maxDD.toFixed(1)} | ${b.calmar.toFixed(3)} | ${b.sharpe.toFixed(2)} | ${b.vol.toFixed(1)} | ¥${Math.round(b.finalCNY / 10000)}万 | ${b.flips}`);
