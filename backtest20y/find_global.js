
// 全球资产配置策略回测 — 与 Q30/Q70 同窗口同口径 (2006-08-21 ~ 2026-08-20, 10万+400/周)
const fs = require('fs');
const FX = 7.25;
const WINDOW = { start: '2006-08-21', end: '2026-08-20' };
function loadEM(path) {
  const j = JSON.parse(fs.readFileSync(path, 'utf8'));
  const raw = j.data ? j.data.klines : j.klines;
  const out = {};
  for (const k of raw) { const p = k.split(','); out[p[0]] = { close: +p[2] }; }
  return out;
}
const NAMES = { QQQ: '纳指100', SPX: '标普500', N225: '日经225', GDAXI: '德国DAX', HSI: '恒生', CN300: '沪深300', GLD: '黄金' };
const ASSETS = Object.keys(NAMES);
const data = {};
for (const a of ASSETS) data[a] = loadEM('global_data/' + a + '.json');
const days = Object.keys(data.QQQ).sort().filter(d => d >= WINDOW.start && d <= WINDOW.end);
const dayIdx = new Map(days.map((d, i) => [d, i]));
// 每个资产自己的交易日序列
const seq = {};
for (const a of ASSETS) { seq[a] = Object.keys(data[a]).sort(); }
const seqIdx = {};
for (const a of ASSETS) { seqIdx[a] = new Map(seq[a].map((d, i) => [d, i])); }
// 每周bar: 以QQQ日历分组, 记录各资产最新可得收盘
function buildWeekly() {
  const bars = []; let cur = null;
  const isoWeek = (d) => { const dt = new Date(d + 'T00:00:00Z'); const day = (dt.getUTCDay() + 6) % 7; dt.setUTCDate(dt.getUTCDate() - day + 3); const firstThu = new Date(Date.UTC(dt.getUTCFullYear(), 0, 4)); const week = 1 + Math.round(((dt - firstThu) / 86400000 - 3 + ((firstThu.getUTCDay() + 6) % 7)) / 7); return dt.getUTCFullYear() + '-' + String(week).padStart(2, '0'); };
  const lastPrice = {}; for (const a of ASSETS) lastPrice[a] = null;
  for (const d of days) {
    const wk = isoWeek(d);
    if (!cur) cur = { week: wk, date: d };
    if (wk !== cur.week) { bars.push(cur); cur = { week: wk, date: d }; }
    cur.date = d;
    for (const a of ASSETS) {
      if (data[a][d]) lastPrice[a] = data[a][d].close;
    }
    cur.p = { ...lastPrice };
  }
  if (cur) bars.push(cur);
  return bars;
}
const bars = buildWeekly();
const n = bars.length;
const init = 100000 / FX, base = 400 / FX;
// 12m动量(跳过最近1月): 资产自身 i-273
function momA(a, d) {
  const i = seqIdx[a].get(d);
  if (i === undefined || i < 273) return 0;
  return data[a][d].close / data[a][seq[a][i - 273]].close - 1;
}
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
// 通用回测: weightsFn(barDate, isME, curWeights) -> 目标权重对象; 仅月末可调仓; 新钱按当前权重买
function run(name, weightsFn, opts = {}) {
  const dcaOnly = !!opts.dcaOnly; // 只改新钱流向, 永不卖旧仓
  const pool = opts.pool || ASSETS;
  const w = {}; for (const a of pool) w[a] = 0;
  let cash = init, flips = 0, actions = 0; const weekly = [], flows = [];
  for (let i = 0; i < n; i++) {
    const b = bars[i];
    const prevValue = weekly.length ? weekly[weekly.length - 1].value : 0;
    cash += base; flows.push({ t: i, amt: base });
    const isME = (i === n - 1 || +bars[i + 1].date.slice(5, 7) !== +b.date.slice(5, 7));
    const priceOf = (a) => (b.p[a] || 0);
    const total = cash + pool.reduce((s, a) => s + w[a] * priceOf(a), 0);
    if (isME) {
      target = weightsFn(b.date, i, w, total, b);
      if (!dcaOnly) {
        // 记录动作
        let changed = false;
        for (const a of pool) { const cur = total > 0 ? w[a] * priceOf(a) / total : 0; if (Math.abs((target[a] || 0) - cur) > 0.005) changed = true; }
        if (changed) { actions++; }
        // 调仓到目标
        for (const a of pool) w[a] = total * (target[a] || 0) / (priceOf(a) || 1);
        cash = total - pool.reduce((s, a) => s + w[a] * priceOf(a), 0);
      } else {
        actions++; // 每月信号切换也计一次"决策"(但只影响新钱)
      }
    } else {
      const cur = target || {};
      for (const a of pool) { const buy = Math.min(cash * (cur[a] || 0), cash); w[a] += buy / (priceOf(a) || 1); cash -= buy; }
    }
    const value = cash + pool.reduce((s, a) => s + w[a] * priceOf(a), 0);
    weekly.push({ value, prevValue, contrib: base });
  }
  const lastBar = bars[n - 1];
  const finalUSD = cash + pool.reduce((s, a) => s + w[a] * (lastBar.p[a] || 0), 0);
  const m = metrics(weekly, flows, finalUSD);
  return { name, xirr: m.xirr, maxDD: m.maxDD, calmar: m.calmar, sharpe: m.sharpe, vol: m.vol, finalCNY: finalUSD * FX, actions };
}
// 12m动量排名
function momRank(d) { const arr = ASSETS.map(a => ({ a, m: momA(a, d) })); arr.sort((x, y) => y.m - x.m); return arr; }
// A: 全球动量 Top1 全仓
const stratA = (d) => { const r = momRank(d); const w = {}; w[r[0].a] = 1; return w; };
// B: 全球动量 Top2 等权
const stratB = (d) => { const r = momRank(d); const w = {}; w[r[0].a] = 0.5; w[r[1].a] = 0.5; return w; };
// C: 全球等权(7资产, 月度再平衡)
const stratC = () => { const w = {}; for (const a of ASSETS) w[a] = 1 / ASSETS.length; return w; };
// D: 新钱定投轮动 Top2 (永不卖旧仓, 新钱按信号分配) — 国内执行友好
const stratD = (d) => { const r = momRank(d); const target = {}; for (const a of ASSETS) target[a] = (a === r[0].a || a === r[1].a) ? 0.5 : 0; return target; };
// E: 风险平价简化: 权重 ∝ 1/波动率(过去252日), 月度调; 现金流不做杠杆(归一化)
function stratE(d) {
  const vol = {}; let sum = 0;
  for (const a of ASSETS) {
    const i = seqIdx[a].get(d);
    const closes = [];
    for (let j = Math.max(0, i - 251); j <= i; j++) closes.push(data[a][seq[a][j]].close);
    let ret = 0; for (let j = 1; j < closes.length; j++) ret += Math.log(closes[j] / closes[j - 1]);
    const mean = ret / (closes.length - 1); let v = 0;
    for (let j = 1; j < closes.length; j++) { const r = Math.log(closes[j] / closes[j - 1]) - mean; v += r * r; }
    vol[a] = Math.sqrt(v / (closes.length - 1)) || 1e-9;
    sum += 1 / vol[a];
  }
  const w = {}; for (const a of ASSETS) w[a] = (1 / vol[a]) / sum;
  return w;
}
// F: 发达市场动量 Top2 (QQQ/SPX/N225/GDAXI/GLD, 去掉恒生/A股)
const DEV = ['QQQ', 'SPX', 'N225', 'GDAXI', 'GLD'];
function momRankPool(d, pool) { const arr = pool.map(a => ({ a, m: momA(a, d) })); arr.sort((x, y) => y.m - x.m); return arr; }
const stratF = (d) => { const r = momRankPool(d, DEV); const w = {}; w[r[0].a] = 0.5; w[r[1].a] = 0.5; return w; };
// G: 全球动量 Top2, 但两者动量都<=0 时持现金(避险)
const stratG = (d) => { const r = momRank(d); const w = {}; if (r[0].m > 0) w[r[0].a] = 0.5; if (r[1].m > 0) w[r[1].a] = 0.5; return w; };
// H: Q30框架+全球卫星: 上行态 50%QQQ+20%日经+30%金; 下行态 15%QQQ+5%日经+30%金+50%现金
const stratH = (d) => { const up = momA('QQQ', d) > 0; const w = { QQQ: up ? 0.5 : 0.15, N225: up ? 0.2 : 0.05, GLD: 0.3 }; return w; };
// I: 静态全球股金: QQQ30/日经15/德股15/黄金25/现金15 (每月调)
const stratI = () => ({ QQQ: 0.3, N225: 0.15, GDAXI: 0.15, GLD: 0.25 });

console.log('===== 全球资产策略回测 2006-08-21~2026-08-20 (同窗口同口径) =====');
const results = [];
const runs = [
  ['A 全球动量Top1全仓(7池)', stratA, {}],
  ['B 全球动量Top2等权(7池)', stratB, {}],
  ['C 全球等权7资产', stratC, {}],
  ['D 新钱定投轮动Top2(不卖仓)', stratD, { dcaOnly: true }],
  ['E 风险平价(波动率倒数)', stratE, {}],
  ['F 发达市场动量Top2(去中港)', stratF, { pool: DEV }],
  ['G 全球动量Top2+全负持现金', stratG, {}],
  ['H Q30框架+日经卫星(动量为门)', stratH, {}],
  ['I 静态全球股金(30/15/15/25/15)', stratI, {}],
];
for (const [name, fn, opts] of runs) {
  const r = run(name, fn, opts);
  results.push(r);
  console.log(`${r.name} | XIRR ${r.xirr.toFixed(2)}% | MaxDD ${r.maxDD.toFixed(1)}% | Calmar ${r.calmar.toFixed(3)} | Sharpe ${r.sharpe.toFixed(2)} | vol ${r.vol.toFixed(1)}% | 终值¥${Math.round(r.finalCNY / 10000)}万 | 调仓${r.actions}次`);
}
console.log('基准: Q30动量 15.21% / 27.9% / 0.545 | Q70金30 15.59% / 36.9% / 0.422');
fs.writeFileSync('results_global.json', JSON.stringify(results, null, 2));
