// gen_q30_data.js — 生成 Q30 动量切换数据（results_q30.json，供 gen_q70_page.py 内嵌）
// 推荐版：动量12m(跳1月) + 上行70/30 + 下行Q30/金30/现金40 + 上下偏离≥5pp才调 + 翻转必调
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
// mode: 'monthly'|'band5'|'fliponly'
function runQ30(mode) {
  const band = mode === 'band5' ? 0.05 : 0;
  const downBand = mode === 'band5' ? 0.05 : 0;
  let qS = 0, gS = 0, cash = init, curUp = true, flips = 0, actions = 0;
  const weekly = [], flows = [], flipLog = [];
  const yearly = {}; let yearVal = null;
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
      if (flip) { curUp = upSig; flips++; flipLog.push({ d: b.date, mQ: +(mQ * 100).toFixed(1), dir: upSig ? 'up' : 'down', qv: Math.round(qS * b.qqq * FX), gv: Math.round(gS * (b.gld ?? 0) * FX), cash: Math.round(cash * FX) }); doReb = true; }
      else if (mode === 'monthly') doReb = true;
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
    const y = +b.date.slice(0, 4);
    if (!yearly[y]) yearly[y] = { year: y, startVal: value, contrib: 0 };
    yearly[y].contrib += base;
    yearly[y].endVal = value;
  }
  const finalUSD = qS * bars[n - 1].qqq + gS * (bars[n - 1].gld ?? 0) + cash;
  const m = metrics(weekly, flows, finalUSD);
  const yearlyTable = Object.values(yearly).map(y => ({ year: y.year, startVal: Math.round(y.startVal * FX), endVal: Math.round(y.endVal * FX), contrib: Math.round(y.contrib * FX), retPct: y.startVal > 0 ? +(((y.endVal - y.startVal - y.contrib) / y.startVal) * 100).toFixed(1) : null }));
  return { xirr: +m.xirr.toFixed(2), maxDD: +m.maxDD.toFixed(1), calmar: +m.calmar.toFixed(3), sharpe: +m.sharpe.toFixed(2), vol: +m.vol.toFixed(1), finalCNY: Math.round(finalUSD * FX), flips, actions, flipLog, yearly: yearlyTable };
}
// 基线：Q70/金30 年度+5%带
function runBase() {
  let qS = init * 0.7 / bars[0].qqq, gS = init * 0.3 / bars[0].gld, cash = 0;
  const weekly = [], flows = [];
  for (let i = 0; i < n; i++) {
    const b = bars[i];
    const prevValue = weekly.length ? weekly[weekly.length - 1].value : 0;
    cash += base; flows.push({ t: i, amt: base });
    const buyQ = Math.min(base * 0.7, cash); qS += buyQ / b.qqq; cash -= buyQ;
    const buyG = Math.min(base * 0.3, cash); gS += buyG / b.gld; cash -= buyG;
    const m = +b.date.slice(5, 7);
    const isME = (i === n - 1 || +bars[i + 1].date.slice(5, 7) !== m);
    if (m === 12 && isME) {
      const total = qS * b.qqq + gS * b.gld + cash;
      const curQ = total > 0 ? qS * b.qqq / total : 0.7;
      if (Math.abs(curQ - 0.7) * 100 >= 5) { qS = total * 0.7 / b.qqq; gS = total * 0.3 / b.gld; cash = total - qS * b.qqq - gS * b.gld; }
    }
    const value = qS * b.qqq + gS * b.gld + cash;
    weekly.push({ value, prevValue, contrib: base });
  }
  const finalUSD = qS * bars[n - 1].qqq + gS * bars[n - 1].gld + cash;
  const m = metrics(weekly, flows, finalUSD);
  return { xirr: +m.xirr.toFixed(2), maxDD: +m.maxDD.toFixed(1), calmar: +m.calmar.toFixed(3), sharpe: +m.sharpe.toFixed(2), vol: +m.vol.toFixed(1), finalCNY: Math.round(finalUSD * FX), flips: 0, actions: 0, flipLog: [], yearly: [] };
}
const q30 = runQ30('band5');
const q30m = runQ30('monthly');
const q30f = runQ30('fliponly');
const baseR = runBase();
const out = {
  generated: '2026-08-23', window: '2006-08-21~2026-08-20',
  q30: { name: 'Q30动量切换(推荐版:偏离5%带)', ...q30 },
  q30_monthly: { name: 'Q30动量切换(原版:每月调)', xirr: q30m.xirr, maxDD: q30m.maxDD, calmar: q30m.calmar, sharpe: q30m.sharpe, vol: q30m.vol, finalCNY: q30m.finalCNY, flips: q30m.flips, actions: q30m.actions },
  q30_fliponly: { name: 'Q30动量切换(只翻转)', xirr: q30f.xirr, maxDD: q30f.maxDD, calmar: q30f.calmar, sharpe: q30f.sharpe, vol: q30f.vol, finalCNY: q30f.finalCNY, flips: q30f.flips, actions: q30f.actions },
  baseline: { name: '旧方案:Q70/金30 年度+5%带', ...baseR },
};
fs.writeFileSync('results_q30.json', JSON.stringify(out, null, 1));
console.log('Q30推荐版', q30.xirr, q30.maxDD, q30.calmar, '终值¥' + Math.round(q30.finalCNY / 10000) + '万', q30.flips + '翻转/' + q30.actions + '动作');
console.log('Q30月调版', q30m.xirr, q30m.maxDD, q30m.calmar, q30m.actions + '动作');
console.log('Q30翻转only', q30f.xirr, q30f.maxDD, q30f.calmar);
console.log('基线', baseR.xirr, baseR.maxDD, baseR.calmar);
console.log('翻转日历', q30.flipLog.map(f => f.d + (f.dir === 'up' ? '上' : '下')).join(' '));

