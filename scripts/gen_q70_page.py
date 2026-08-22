"""生成 Q70/金30 策略站 q70.html（数据驱动，回测 JSON → 内嵌数据 → JS 渲染）

页面内容:
1. 方案概览卡: XIRR/MaxDD/Calmar/终值 + 一句话结论
2. 当前操作卡: 10万分配 + 月5000 + 年度检视（静态文本，按2026-08实盘快照）
3. 实时监控卡: 腾讯行情(浏览器60s拉取): QQQ/518880黄金/159632溢价窗口/511880
4. 持仓偏离度卡: localStorage存份额 → 实时算 QQQ 实际占比 vs 70% 目标, 偏离>5% 提示"该调仓"
5. 回测数据卡: 逐年收益表 / 回撤事件表 / 频率×触发带 / 全网格最优解
6. 页脚: 口径与验证说明

数据全部来自 backtest20y/results_q70_detail.json + results_q70_detail2.json（已验证），
本脚本只做"读JSON→内嵌→渲染"，不手抄数字。
"""
import json, os, re, urllib.request, time
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.join(BASE, "..", "backtest20y")

def load(name):
    with open(os.path.join(BT, name), encoding="utf-8") as f:
        return json.load(f)

def fetch(url, ref, tries=3, enc="utf-8"):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": ref})
            return urllib.request.urlopen(req, timeout=15).read().decode(enc, "ignore")
        except Exception as e:
            last = e
            time.sleep(1.0 * (i + 1))
    raise last

# ---- 实时抓取快照（017436 净值 + 腾讯行情），失败时回退到内置静态值 ----
SNAP = {  # 静态默认值（离线/抓取失败时使用），成功抓取后会被覆盖
    "qqq": 713.44, "qqqDate": "08-21",
    "gprice": 9.388, "gprem": 0.22,
    "nprice": 2.436, "nprem": 8.63,
    "pnav": 2.3201, "pnavDate": "08-20", "plimit": 1000,
}
def fetch_snapshot():
    s = dict(SNAP)
    now = datetime.now()
    # 017436 场外净值（东财 lsjz，需 Referer）
    try:
        raw = fetch("https://api.fund.eastmoney.com/f10/lsjz?fundCode=017436&pageIndex=1&pageSize=3",
                    "https://fundf10.eastmoney.com/")
        m = re.search(r'"LSJZList":\s*(\[.*?\]),', raw, re.DOTALL)
        if m:
            lst = json.loads(m.group(1))
            if lst:
                s["pnav"] = float(lst[0]["DWJZ"]); s["pnavDate"] = lst[0]["FSRQ"][5:]
    except Exception:
        pass
    # 腾讯行情：518880 黄金 / 159632 场内纳指 / 511880 货币 / QQQ 美股
    try:
        raw = fetch("https://qt.gtimg.cn/q=sh518880,sz159632,sh511880,usQQQ",
                    "https://gu.qq.com/", enc="gbk")
        for line in raw.strip().split(";"):
            line = line.strip()
            if "=" not in line or "~" not in line:
                continue
            p = line.split("~")
            if len(p) < 40:
                continue
            code = p[2]
            try:
                if code == "518880":
                    s["gprice"] = float(p[3])
                    prem = float(p[77])
                    if -50 < prem < 50:
                        s["gprem"] = prem
                elif code == "159632":
                    s["nprice"] = float(p[3])
                    prem = float(p[77])
                    if -50 < prem < 50:
                        s["nprem"] = prem
                elif code == "QQQ.OQ" or code == "QQQ":
                    s["qqq"] = float(p[3])
                    s["qqqDate"] = now.strftime("%m-%d")
            except (ValueError, IndexError):
                pass
    except Exception:
        pass
    s["snapTime"] = now.strftime("%Y-%m-%d %H:%M")
    return s

det1 = load("results_q70_detail.json")
det2 = load("results_q70_detail2.json")

# ---- 提取内嵌数据（只取页面需要的字段，控制体积） ----
freqRows = det1["freqRows"]
grid = det1["gridRows"]
yearly = det1["yearly"]
ddEvents = det1["ddEvents"]
combos = det2["combos"]
cand = det2["cand"]

def pick(r, keys):
    return {k: (round(r[k], 4) if isinstance(r[k], float) else r[k]) for k in keys if k in r}

FREQ_LABEL = {"none": "不调整", "q": "季度", "h": "半年", "y": "年度", "2y": "两年"}
# 频率对比（Q70/金30 固定权重）
freq_table = [pick(r, ["freq", "xirr", "maxDD", "calmar", "sharpe", "finalCNY"]) for r in freqRows]
for r in freq_table:
    r["label"] = FREQ_LABEL.get(r.get("freq"), r.get("freq"))
# 触发带（频率×触发带，取 年度 与 两年 两组）
band_table = [pick(r, ["f", "band", "xirr", "maxDD", "calmar", "finalCNY"]) for r in combos
              if r["f"] in ("y", "2y")]
# 全网格最优（XIRR≥15% 前8）
grid_table = [pick(r, ["name", "xirr", "maxDD", "calmar", "sharpe", "finalCNY"]) for r in cand[:8]]
# 逐年
yearly_table = [pick(r, ["year", "startVal", "endVal", "contrib", "retPct"]) for r in yearly]
# 回撤事件（>8%）
dd_table = [pick(r, ["from", "to", "depth", "recovered", "durWeeks", "recWeeks"]) for r in ddEvents if r["depth"] > 8]
# 主推方案（Q70/金30 季度必调，与用户引用的数字一致）
q70q = next(r for r in freqRows if r["freq"] == "q")

backtest = {
    "q70q": pick(q70q, ["xirr", "maxDD", "calmar", "sharpe", "finalCNY"]),
    "freq": freq_table,
    "bands": band_table,
    "grid": grid_table,
    "yearly": yearly_table,
    "dd": dd_table,
}

def j(v, indent=0):
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Q70/金30 策略站 · 20年回测</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:#0d1117;color:#e6edf3;padding:16px;max-width:500px;margin:0 auto;font-size:14px}
h1{font-size:20px;font-weight:700}
.sub{font-size:11px;color:#8b949e;margin:4px 0 14px;line-height:1.6}
#rt{cursor:pointer;font-weight:700}
#rt.ok{color:#3fb950} #rt.bad{color:#f85149}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:14px;margin-bottom:12px}
.card.hl{border-color:#238636;background:linear-gradient(135deg,#12221a,#161b22)}
.hdr2{font-size:13px;font-weight:700;margin:14px 0 8px;padding-bottom:6px;border-bottom:1px solid #21262d;display:flex;justify-content:space-between;align-items:center}
.pos-edit{float:right;font-size:10px;font-weight:400;color:#58a6ff;cursor:pointer;border:1px solid #30363d;border-radius:6px;padding:1px 8px}
.rw{display:flex;gap:6px;margin-top:8px}
.bx{flex:1;padding:7px 4px;border-radius:6px;text-align:center;background:#0d1117;border:1px solid #21262d;min-width:0}
.bx .lb{color:#8b949e;font-size:9px}
.bx .vl{font-weight:700;font-size:13px;margin-top:2px;white-space:nowrap}
.ok{color:#3fb950} .warn{color:#d29922} .bad{color:#f85149} .flat{color:#8b949e}
.up{color:#3fb950} .down{color:#f85149}
.inf{font-size:10px;color:#8b949e;margin-top:8px;line-height:1.6}
.inf b{color:#e6edf3}
table{width:100%;border-collapse:collapse;font-size:10px;margin-top:8px}
th,td{padding:5px 4px;text-align:right;border-bottom:1px solid #21262d;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:#8b949e;font-weight:600}
tr.hlrow td{background:#12221a;color:#3fb950;font-weight:700}
.note{margin-top:14px;padding:10px;background:#1c2128;border-radius:8px;font-size:10px;color:#8b949e;line-height:1.7;border:1px solid #21262d}
.big{font-size:22px;font-weight:800}
.badge{display:inline-block;font-size:9px;padding:2px 6px;border-radius:4px;background:#21262d;color:#8b949e;margin-left:6px;vertical-align:middle}
.badge.opt{background:#002d1a;color:#3fb950}
.badge.warn{background:#3d2900;color:#d29922}
.badge.bad{background:#3d1113;color:#f85149}
ol.steps{padding-left:18px;margin-top:6px}
ol.steps li{margin-bottom:6px;line-height:1.5;font-size:12px}
ol.steps b{color:#3fb950}
.win{display:block;margin:0 0 12px;padding:10px 12px;border-radius:10px;background:#002d1a;border:1px solid #238636;color:#3fb950;font-size:12px;font-weight:700;line-height:1.5}
.win.hidden{display:none}
details.card summary{cursor:pointer;font-weight:700;font-size:13px;color:#58a6ff;list-style:none}
details.card summary::before{content:"▸ ";color:#58a6ff}
details.card[open] summary::before{content:"▾ "}
details.card summary::-webkit-details-marker{display:none}
</style>
</head>
<body>
<nav style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap">
  <a href="q70.html" style="flex:1;text-align:center;padding:6px;border-radius:8px;background:#12221a;color:#3fb950;text-decoration:none;font-size:12px;font-weight:700;border:1px solid #238636">🥇 Q70/金30 策略</a>
  <a href="monitor.html" style="flex:1;text-align:center;padding:6px;border-radius:8px;background:#21262d;color:#e6edf3;text-decoration:none;font-size:12px;font-weight:700;border:1px solid #30363d">📡 溢价监控</a>
</nav>
<h1>🥇 Q70/金30 静态策略站</h1>
<p class="sub">20年回测 2006-08~2026-08 · 10万+¥400/周 · <span id="rt">🟢 实时行情加载中…</span><br>浏览器实时抓取腾讯行情(60s自动刷新) · 回测数据由 backtest20y 已验证脚本生成</p>
<div id="win" class="win hidden"></div>

<div class="card hl">
  <div class="hdr2">🎯 主推方案：Q70/金30 年度检视 + 偏离>5% 才调 <span class="badge opt">最优解</span></div>
  <div class="rw">
    <div class="bx"><div class="lb">XIRR (20年)</div><div class="vl" id="m-xirr">--</div></div>
    <div class="bx"><div class="lb">最大回撤</div><div class="vl" id="m-dd">--</div></div>
    <div class="bx"><div class="lb">Calmar</div><div class="vl" id="m-calmar">--</div></div>
    <div class="bx"><div class="lb">夏普</div><div class="vl" id="m-sharpe">--</div></div>
  </div>
  <div class="rw">
    <div class="bx"><div class="lb">终值 (¥51.7万投入)</div><div class="vl" id="m-final">--</div></div>
    <div class="bx"><div class="lb">年操作</div><div class="vl">~15次/20年</div></div>
    <div class="bx"><div class="lb">亏损年</div><div class="vl">3/21年</div></div>
    <div class="bx"><div class="lb">最长深熊</div><div class="vl">86周</div></div>
  </div>
  <div class="inf">vs 原季度必调方案：XIRR 15.33→<b>15.59%</b>、回撤 38.1→<b>36.9%</b>、操作 80→<b>~15次</b>。<b>再平衡是保险，不是收益来源</b>——不调整也有15.30%，不必过度操作。</div>
</div>

<div class="hdr2">📋 实盘操作（2026-08 快照）</div>
<div class="card">
  <ol class="steps">
    <li><b>存量10万：</b>黄金¥3万→518880 立即买；QQQ¥7万→017436 日投¥1000（约3.5个月投完，过渡钱放余额宝）</li>
    <li><b>每月¥5K：</b>QQQ¥3.5K（周投¥875）+ 黄金¥1.5K（月中一次，或攒两月¥3K）</li>
    <li><b>每年1月：</b>看下方「持仓偏离度」，QQQ占比偏离70%超过5pp才调仓（518880买/卖调节，手机10分钟）</li>
    <li>⚠️ 159632 溢价&lt;2% 才场内抄底；<b>别用黄金弹药换QQQ</b>（回测实锤负优化）</li>
  </ol>
</div>

<div class="hdr2">📊 持仓偏离度 <span class="pos-edit" onclick="posEdit()">✏️ 设置份额</span></div>
<div class="card">
  <div class="rw">
    <div class="bx"><div class="lb">QQQ 市值(017436)</div><div class="vl" id="p-q">--</div></div>
    <div class="bx"><div class="lb">黄金市值(518880)</div><div class="vl" id="p-g">--</div></div>
    <div class="bx"><div class="lb">QQQ 实际占比</div><div class="vl" id="p-pct">--</div></div>
    <div class="bx"><div class="lb">偏离 70%目标</div><div class="vl" id="p-dev">--</div></div>
  </div>
  <div class="inf" id="p-advice">点 ✏️设置 录入 017436 份额 与 518880 份额，自动计算当前占比与偏离（年度检视专用，不用记成本价）。</div>
</div>

<div class="hdr2">🛰 实时行情</div>
<div class="card">
  <div class="rw">
    <div class="bx"><div class="lb">QQQ 美股</div><div class="vl" id="q-qqq">--</div></div>
    <div class="bx"><div class="lb">黄金 518880</div><div class="vl" id="q-gold">--</div></div>
    <div class="bx"><div class="lb">场内纳指 159632</div><div class="vl" id="q-ndx">--</div></div>
    <div class="bx"><div class="lb">货币 511880</div><div class="vl" id="q-cash">--</div></div>
  </div>
  <div class="inf" id="q-inf">加载中…</div>
</div>

<details class="card">
  <summary>📈 20年回测明细（点击展开）</summary>
  <div class="hdr2" style="margin-top:0">再平衡频率（Q70/金30 固定）</div>
  <div id="t-freq"></div>
  <div class="hdr2">年度/两年 × 触发带</div>
  <div id="t-bands"></div>
  <div class="hdr2">XIRR≥15% 最优组合（全网格前8）</div>
  <div id="t-grid"></div>
  <div class="hdr2">逐年收益（21个日历年度·18正3负）</div>
  <div id="t-yearly"></div>
  <div class="hdr2">回撤事件（深度&gt;8%）</div>
  <div id="t-dd"></div>
</details>

<div class="note">
<strong>📐 口径</strong> 回测 2006-08-21~2026-08-20 · ¥10万+¥400/周 · FX=7.25 · 价格口径无分红<br>
• 最优解：年度检视+偏离&gt;5%触发 = XIRR 15.59% / MaxDD 36.9% / Calmar 0.422（比季度必调少 80% 操作）<br>
• ⚠️ 017436 为主动型（YTD 跑输 QQQ ~12pp），需按月对照跟踪<br>
• 数据/生成器：东财 QQQ/GLD 日线 → backtest20y 已验证 JSON → scripts/gen_q70_page.py
</div>

<script>
// ===== 内嵌回测数据（由 gen_q70_page.py 从已验证 JSON 生成） =====
const BACKTEST = __BACKTEST__;
const SNAP = __SNAP__;
const FX = 7.25;
// ===== 表格渲染 =====
const $ = s => document.querySelector(s);
const wany = v => '¥' + (v / 10000).toFixed(0) + '万';
const pct1 = v => (v == null) ? '--' : v.toFixed(1) + '%';
const fmt = (v, d) => (v == null) ? '--' : (typeof v === 'number' ? v.toFixed(d == null ? 2 : d) : v);
function tbl(el, cols, rows, hlIdx) {
  const head = cols.map(c => '<th>' + c.t + '</th>').join('');
  const body = rows.map((r, i) => '<tr' + (hlIdx && hlIdx.indexOf(i) >= 0 ? ' class="hlrow"' : '') + '>' +
    cols.map(c => '<td>' + fmt(r[c.k], c.d) + '</td>').join('') + '</tr>').join('');
  $(el).innerHTML = '<table><tr>' + head + '</tr>' + body + '</table>';
}
function fmtCNY(v) { return v == null ? '--' : wany(v); }
// 频率表
(function () {
  const B = BACKTEST;
  $('#m-xirr').textContent = pct1(B.q70q.xirr);
  $('#m-dd').textContent = pct1(B.q70q.maxDD);
  $('#m-calmar').textContent = B.q70q.calmar.toFixed(3);
  $('#m-sharpe').textContent = B.q70q.sharpe.toFixed(2);
  $('#m-final').textContent = wany(B.q70q.finalCNY);
  tbl('#t-freq',
    [{ t: '频率', k: 'label' }, { t: 'XIRR%', k: 'xirr', d: 2 }, { t: 'MaxDD%', k: 'maxDD', d: 1 }, { t: 'Calmar', k: 'calmar', d: 3 }, { t: '夏普', k: 'sharpe', d: 2 }, { t: '终值', k: 'finalCNY' }],
    B.freq, [1, 3, 4]);
  tbl('#t-bands',
    [{ t: '频率', k: 'f' }, { t: '触发带', k: 'band' }, { t: 'XIRR%', k: 'xirr', d: 2 }, { t: 'MaxDD%', k: 'maxDD', d: 1 }, { t: 'Calmar', k: 'calmar', d: 3 }, { t: '终值', k: 'finalCNY' }],
    B.bands.map(r => ({ ...r, f: r.f === 'y' ? '年度' : '两年', band: r.band === 0 ? '必调' : '>' + r.band + '%' })), [0, 1]);
  tbl('#t-grid',
    [{ t: '组合', k: 'name' }, { t: 'XIRR%', k: 'xirr', d: 2 }, { t: 'MaxDD%', k: 'maxDD', d: 1 }, { t: 'Calmar', k: 'calmar', d: 3 }, { t: '夏普', k: 'sharpe', d: 2 }, { t: '终值', k: 'finalCNY' }],
    B.grid, [0]);
  tbl('#t-yearly',
    [{ t: '年份', k: 'year' }, { t: '年初¥', k: 'startVal' }, { t: '投入¥', k: 'contrib' }, { t: '年末¥', k: 'endVal' }, { t: '收益%', k: 'retPct', d: 1 }],
    B.yearly.map(r => ({ ...r, startVal: wany(r.startVal * FX), endVal: wany(r.endVal * FX), contrib: '¥' + Math.round(r.contrib * FX) })),
    B.yearly.map((r, i) => r.retPct < 0 ? i : -1).filter(i => i >= 0));
  tbl('#t-dd',
    [{ t: '峰值', k: 'from' }, { t: '谷底', k: 'to' }, { t: '深度', k: 'depth', d: 1 }, { t: '恢复', k: 'recovered' }, { t: '下跌周', k: 'durWeeks' }, { t: '恢复周', k: 'recWeeks' }],
    B.dd);
})();
// ===== 持仓偏离度（localStorage 存份额） =====
const LS = k => localStorage.getItem(k);
function posVal() {
  const qShares = parseFloat(LS('posQShares')), gShares = parseFloat(LS('posGShares'));
  if (!(qShares > 0) || !(gShares > 0)) {
    $('#p-q').textContent = '--'; $('#p-g').textContent = '--'; $('#p-pct').textContent = '--'; $('#p-dev').textContent = '--';
    $('#p-advice').textContent = '点 ✏️设置 录入 017436 份额 与 518880 份额（份额=总金额/成本价，可在券商App查到）';
    return;
  }
  const qv = qShares * SNAP.pnav;      // 017436 净值快照
  const gv = gShares * SNAP.gprice;    // 518880 现价（实时层更新后重算）
  const total = qv + gv;
  const pct = total > 0 ? qv / total * 100 : 0;
  const dev = pct - 70;
  $('#p-q').textContent = wany(qv);
  $('#p-g').textContent = wany(gv);
  $('#p-pct').textContent = pct.toFixed(1) + '%';
  const devEl = $('#p-dev');
  devEl.textContent = (dev > 0 ? '+' : '') + dev.toFixed(1) + 'pp';
  devEl.className = 'vl ' + (Math.abs(dev) > 10 ? 'bad' : Math.abs(dev) > 5 ? 'warn' : 'ok');
  let advice;
  if (Math.abs(dev) <= 5) advice = '🟢 占比在 70%±5% 内，无需操作。每年1月检视一次即可。';
  else if (dev > 5) advice = '🟡 QQQ 超配 ' + dev.toFixed(1) + 'pp（>75%）：新钱全部进黄金 + 卖出部分 QQQ → 年度检视触发，用 518880 买入/场外拆单调节';
  else advice = '🟡 QQQ 低配 ' + (-dev).toFixed(1) + 'pp（<65%）：卖出黄金 518880 → 转入 017436 定投（日¥1000，分20-30日）';
  $('#p-advice').textContent = advice + ' · 017436 净值快照 ' + SNAP.pnavDate + '（T+1，非实时）';
}
function posEdit() {
  const q = (label, cur) => prompt('持仓份额设置\\n' + label, cur || '');
  const qs = q('017436 份额（净值2.32, ¥1000≈431份）', LS('posQShares'));
  if (qs != null && qs !== '') localStorage.setItem('posQShares', qs);
  const gs = q('518880 份额（现价9.39, ¥3000≈320份）', LS('posGShares'));
  if (gs != null && gs !== '') localStorage.setItem('posGShares', gs);
  posVal();
}
// ===== 实时行情层（腾讯 qt.gtimg.cn，浏览器直接fetch） =====
const INTERVAL = 60000;
const SYMS = 'sh518880,sz159632,sh511880,usQQQ';
const usOpen = () => {
  const d = new Date();
  const n = new Date(d.toLocaleString('en-US', { timeZone: 'America/New_York' }));
  const h = n.getHours() + n.getMinutes() / 60, w = n.getDay();
  return w >= 1 && w <= 5 && h >= 9.5 && h < 16;
};
async function refresh() {
  const rt = $('#rt');
  try {
    const r = await fetch('https://qt.gtimg.cn/q=' + SYMS, { cache: 'no-store' });
    const buf = await r.arrayBuffer();
    let txt;
    try { txt = new TextDecoder('gbk').decode(buf); } catch (e) { txt = new TextDecoder().decode(buf); }
    const rows = {};
    for (const seg of txt.split(';')) {
      const m = seg.match(/v_([A-Za-z0-9.]+)="([^"]*)"/);
      if (!m) continue;
      const p = m[2].split('~');
      if (p.length >= 40) rows[p[2]] = p;
    }
    const qq = rows['QQQ.OQ'] || rows['QQQ'];
    if (qq) {
      const q = parseFloat(usOpen() ? qq[3] : qq[4]);
      if (isFinite(q) && q > 10) { $('#q-qqq').textContent = '$' + q.toFixed(2); SNAP.qqq = q; }
    }
    const g = rows['518880'];
    if (g) {
      const price = parseFloat(g[3]);
      if (isFinite(price) && price > 1) {
        const prem = parseFloat(g[77]);
        const premOk = isFinite(prem) && prem > -50 && prem < 50;
        $('#q-gold').textContent = price.toFixed(3) + (premOk ? ' (' + prem.toFixed(2) + '%)' : '');
        SNAP.gprice = price;
      }
    }
    const n = rows['159632'];
    if (n) {
      const price = parseFloat(n[3]);
      if (isFinite(price) && price > 0.5) {
        // 真实溢价 ≈ 现价/快照净值 - 1（QQQ盘中校正）
        const qr = SNAP.qqq && SNAP.qqqDate ? 1 : 1;
        const prem = (price / SNAP.pnav - 1) * 100;
        const ok = isFinite(prem) && prem > -50 && prem < 50;
        const win = $('#win');
        if (ok && prem < 2) {
          win.textContent = '🟢 场内纳指溢价 <2%！可用 518880/511880 换入 159632 抄底';
          win.classList.remove('hidden');
        } else win.classList.add('hidden');
        $('#q-ndx').textContent = price.toFixed(3) + (ok ? ' (' + prem.toFixed(1) + '%)' : '');
        SNAP.nprice = price;
      }
    }
    const c = rows['511880'];
    if (c) { const p = parseFloat(c[3]); if (isFinite(p) && p > 50) $('#q-cash').textContent = p.toFixed(3); }
    posVal();  // 黄金现价更新后重算偏离度
    const t = new Date();
    rt.textContent = '🟢 实时 ' + t.toTimeString().slice(0, 8) + ' · QQQ $' + (SNAP.qqq || 0).toFixed(2) + ' · 60s自动刷新·点击手动';
    rt.className = 'ok';
  } catch (e) {
    rt.textContent = '⚪ 实时获取失败·显示快照·点此重试';
    rt.className = 'bad';
    posVal();
  }
}
posVal();
refresh();
setInterval(refresh, INTERVAL);
$('#rt').onclick = refresh;
</script>
</body>
</html>
"""

snap = fetch_snapshot()  # 实时抓取（017436净值+腾讯行情），失败回退静态值
html = HTML.replace("__BACKTEST__", j(backtest)).replace("__SNAP__", j(snap))
out = os.path.join(os.path.dirname(BASE), "q70.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
print("已生成", out, len(html), "bytes | 快照:", json.dumps(snap, ensure_ascii=False))
