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
// band>0: 上行态每月检查，|QQQ占比-70%|≥band*100才调回70/30；下行态只在翻转时调（Q30），金维持30%可用518880调
function runBand(band, downBand) {
  let qS = 0, gS = 0, cash = init, curUp = true, flips = 0, actions = 0;
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
      const st0 = { total: qS * b.qqq + gS * (b.gld ?? 0) + cash };
      const curQ = st0.total > 0 ? qS * b.qqq / st0.total : qT;
      const flip = upSig !== curUp;
      let doReb = false;
      if (flip) { curUp = upSig; flips++; doReb = true; }
      else if (upSig) doReb = Math.abs(curQ - 0.7) >= band;
      else if (downBand) doReb = Math.abs(curQ - 0.3) >= downBand;
      if (doReb) {
        const st = { total: qS * b.qqq + gS * (b.gld ?? 0) + cash };
        qS = st.total * qT / b.qqq; gS = st.total * gT / (b.gld ?? 1); cash = st.total - qS * b.qqq - gS * (b.gld ?? 0);
        actions++;
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
  return { xirr: m.xirr, maxDD: m.maxDD, calmar: m.calmar, sharpe: m.sharpe, vol: m.vol, finalCNY: finalUSD * FX, flips, actions };
}
console.log('动量12m Q30 变体 | XIRR% | MaxDD% | Calmar | 夏普 | 波动% | 终值¥ | 翻转 | 调仓动作');
console.log(`回测版(每月调) | ${runBand(0,0).xirr.toFixed(2)} | ${runBand(0,0).maxDD.toFixed(1)} | ${runBand(0,0).calmar.toFixed(3)} | ${runBand(0,0).sharpe.toFixed(2)} | ${runBand(0,0).vol.toFixed(1)} | ¥${Math.round(runBand(0,0).finalCNY/10000)}万 | ${runBand(0,0).flips} | ${runBand(0,0).actions}`);
for (const band of [0.03, 0.05, 0.07, 0.10]) {
  const r = runBand(band, 0);
  console.log(`上行偏离≥${(band*100).toFixed(0)}pp才调 | ${r.xirr.toFixed(2)} | ${r.maxDD.toFixed(1)} | ${r.calmar.toFixed(3)} | ${r.sharpe.toFixed(2)} | ${r.vol.toFixed(1)} | ¥${Math.round(r.finalCNY/10000)}万 | ${r.flips} | ${r.actions}`);
}
const r2 = runBand(0.05, 0.05);
console.log(`上下都≥5pp才调 | ${r2.xirr.toFixed(2)} | ${r2.maxDD.toFixed(1)} | ${r2.calmar.toFixed(3)} | ${r2.sharpe.toFixed(2)} | ${r2.vol.toFixed(1)} | ¥${Math.round(r2.finalCNY/10000)}万 | ${r2.flips} | ${r2.actions}`);
