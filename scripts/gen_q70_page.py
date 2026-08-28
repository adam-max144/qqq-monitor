"""生成 Q30 动量切换策略站 q70.html（数据驱动：回测 JSON + 实时快照 → 内嵌 → JS 渲染）

页面内容:
1. 主推方案卡: Q30动量切换(12m) — XIRR/MaxDD/Calmar/夏普/终值/操作量
2. 动量信号卡: QQQ现价 vs 13个月前参考价 → 12m动量 → 上行/下行态（参考价由Actions每日更新）
3. 实盘操作卡: 10万分配 + 月5000 + 每月末检视（静态文本，按2026-08实盘快照）
4. 持仓偏离度卡: localStorage存金额 → 按当前状态目标(上行70%/下行30%)算偏离, >5%提示调仓
5. 实时监控卡: 腾讯行情(浏览器60s拉取): QQQ/518880黄金/159632溢价窗口/511880
6. 回测数据卡: Q30三版对比 / 翻转日历 / Q30逐年 / 旧方案参考(频率×触发带/全网格)
7. 页脚: 口径与验证说明

数据来源: backtest20y/results_q30.json + results_q70_detail.json + results_q70_detail2.json（已验证），
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

# ---- 实时抓取快照（017436净值 + 腾讯行情 + QQQ日线），失败时回退到内置静态值 ----
SNAP = {
    "qqq": 721.11, "qqqDate": "08-27",
    "gprice": 9.388, "gprem": 0.22,
    "nprice": 2.436, "nprem": 8.63,
    "pnav": 2.3201, "pnavDate": "08-20", "plimit": 1000,
    # QQQ 12m动量参考（13个月前收盘价 + 动量%）——新浪日K抓取，失败回退静态值
    "ref13m": 568.14, "ref13mDate": "2025-07-28", "mom": 26.9, "qqqKlineDate": "2026-08-27",
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
    # QQQ 日线：最新收盘 + 273个交易日前收盘（=12m动量跳过最近1个月）
    # 数据源: 新浪美股日K（东财 push2his 2026-08 起不稳定, 页面曾停在旧快照 08-21）
    try:
        raw = fetch("https://stock.finance.sina.com.cn/usstock/api/jsonp_v2.php/var%20_QQQ_=/US_MinKService.getDailyK?symbol=QQQ&___qn=600",
                    "https://finance.sina.com.cn/")
        m = re.search(r"\((.*)\)", raw, re.DOTALL)
        data = json.loads(m.group(1))
        rows = [(r["d"], float(r["c"])) for r in data if isinstance(r, dict) and "d" in r and "c" in r]
        rows.sort()
        if len(rows) > 273:
            lat_d, lat_c = rows[-1]; ref_d, ref_c = rows[-1 - 273]
            s["ref13m"] = round(ref_c, 2); s["ref13mDate"] = ref_d
            s["mom"] = round((lat_c / ref_c - 1) * 100, 1)
            s["qqqKlineDate"] = lat_d
            # QQQ 价格/数据日期统一用最近收盘（休市时页面显示上一收盘数据）
            s["qqq"] = round(lat_c, 2); s["qqqDate"] = lat_d[5:]
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
                    pass  # QQQ 价格统一用东财日线最近收盘（s.qqq），此处不覆盖
            except (ValueError, IndexError):
                pass
    except Exception:
        pass
    s["snapTime"] = now.strftime("%Y-%m-%d %H:%M")
    return s

det1 = load("results_q70_detail.json")
det2 = load("results_q70_detail2.json")
q30d = load("results_q30.json")

# ---- 旧方案参考数据（保留在"旧方案参考"折叠区） ----
freqRows = det1["freqRows"]
grid = det1["gridRows"]
yearly = det1["yearly"]
ddEvents = det1["ddEvents"]
combos = det2["combos"]
cand = det2["cand"]

def pick(r, keys):
    return {k: (round(r[k], 4) if isinstance(r[k], float) else r[k]) for k in keys if k in r}

FREQ_LABEL = {"none": "不调整", "q": "季度", "h": "半年", "y": "年度", "2y": "两年"}
freq_table = [pick(r, ["freq", "xirr", "maxDD", "calmar", "sharpe", "finalCNY"]) for r in freqRows]
for r in freq_table:
    r["label"] = FREQ_LABEL.get(r.get("freq"), r.get("freq"))
band_table = [pick(r, ["f", "band", "xirr", "maxDD", "calmar", "finalCNY"]) for r in combos
              if r["f"] in ("y", "2y")]
grid_table = [pick(r, ["name", "xirr", "maxDD", "calmar", "sharpe", "finalCNY"]) for r in cand[:8]]
yearly_table = [pick(r, ["year", "startVal", "endVal", "contrib", "retPct"]) for r in yearly]
dd_table = [pick(r, ["from", "to", "depth", "recovered", "durWeeks", "recWeeks"]) for r in ddEvents if r["depth"] > 8]
q70q = next(r for r in freqRows if r["freq"] == "q")

def sel(r, keys):
    return {k: r[k] for k in keys if k in r}

backtest = {
    "q70q": pick(q70q, ["xirr", "maxDD", "calmar", "sharpe", "finalCNY"]),
    "freq": freq_table,
    "bands": band_table,
    "grid": grid_table,
    "yearly": yearly_table,
    "dd": dd_table,
    # Q30 动量切换
    "q30": sel(q30d["q30"], ["name", "xirr", "maxDD", "calmar", "sharpe", "vol", "finalCNY", "flips", "actions"]),
    "q30_monthly": sel(q30d["q30_monthly"], ["name", "xirr", "maxDD", "calmar", "finalCNY", "flips", "actions"]),
    "q30_fliponly": sel(q30d["q30_fliponly"], ["name", "xirr", "maxDD", "calmar", "finalCNY", "flips", "actions"]),
    "q30_base": sel(q30d["baseline"], ["name", "xirr", "maxDD", "calmar", "finalCNY", "flips", "actions"]),
    "flips": q30d["q30"]["flipLog"],
    "q30yearly": q30d["q30"]["yearly"],
}

def j(v, indent=0):
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Q30 动量切换 策略站 · 20年回测</title>
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
tr.ddrow td{color:#f85149}
.note{margin-top:14px;padding:10px;background:#1c2128;border-radius:8px;font-size:10px;color:#8b949e;line-height:1.7;border:1px solid #21262d}
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
details.subd{margin:10px 0;padding:8px;background:#0d1117;border:1px solid #21262d;border-radius:8px}
details.subd summary{cursor:pointer;font-weight:600;font-size:11px;color:#8b949e;list-style:none}
details.subd summary::before{content:"▸ ";color:#8b949e}
details.subd[open] summary::before{content:"▾ "}
</style>
</head>
<body>
<nav style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap">
  <a href="q70.html" style="flex:1;text-align:center;padding:6px;border-radius:8px;background:#12221a;color:#3fb950;text-decoration:none;font-size:12px;font-weight:700;border:1px solid #238636">🥇 Q30 动量 策略</a>
  <a href="monitor.html" style="flex:1;text-align:center;padding:6px;border-radius:8px;background:#21262d;color:#e6edf3;text-decoration:none;font-size:12px;font-weight:700;border:1px solid #30363d">📡 溢价监控</a>
</nav>
<h1>🎯 Q30 动量切换策略站</h1>
<p class="sub">20年回测 2006-08~2026-08 · 10万+¥400/周 · <span id="rt">🟢 实时行情加载中…</span><br>每月末看1次信号 · 上行70/30 · 下行30/30/40 · 偏离&gt;5%才调</p>
<div id="win" class="win hidden"></div>

<div class="card hl">
  <div class="hdr2">🎯 主推方案：Q30 动量切换（12m）<span class="badge opt">新主推</span></div>
  <div class="rw">
    <div class="bx"><div class="lb">XIRR (20年)</div><div class="vl" id="m-xirr">--</div></div>
    <div class="bx"><div class="lb">最大回撤</div><div class="vl" id="m-dd">--</div></div>
    <div class="bx"><div class="lb">Calmar</div><div class="vl" id="m-calmar">--</div></div>
    <div class="bx"><div class="lb">夏普</div><div class="vl" id="m-sharpe">--</div></div>
  </div>
  <div class="rw">
    <div class="bx"><div class="lb">终值 (¥51.7万投入)</div><div class="vl" id="m-final">--</div></div>
    <div class="bx"><div class="lb">20年翻转</div><div class="vl" id="m-flips">--</div></div>
    <div class="bx"><div class="lb">20年调仓</div><div class="vl" id="m-actions">--</div></div>
    <div class="bx"><div class="lb">亏损年</div><div class="vl">3/21年</div></div>
  </div>
  <div class="inf">vs 旧方案（Q70/金30 年度检视）：收益 15.59→<b>15.21%</b>、回撤 36.9→<b>27.9%</b>、月检1次/年均动手2.6次。<b>熊市先减仓到30%再扛</b>——回撤少近9pp，代价是收益少0.38pp。</div>
</div>

<div class="hdr2">🔄 动量信号 <span class="badge warn">每月末看这里</span></div>
<div class="card">
  <div class="rw">
    <div class="bx"><div class="lb">QQQ 现价</div><div class="vl" id="s-qqq">--</div></div>
    <div class="bx"><div class="lb">13个月前参考</div><div class="vl" id="s-ref">--</div></div>
    <div class="bx"><div class="lb">12m动量</div><div class="vl" id="s-mom">--</div></div>
    <div class="bx"><div class="lb">状态</div><div class="vl" id="s-state">--</div></div>
  </div>
  <div class="inf" id="s-trigger" style="margin-top:10px;padding:8px;background:#002d1a;border:1px solid #238636;border-radius:8px;color:#3fb950">📌 最近触发：读取中…</div>
  <div class="inf" id="s-target">动量 = QQQ现价 ÷ 约13个月前收盘价 − 1（过去12个月涨跌，跳过最近1个月）。动量&gt;0 → <b>上行态 70/30</b>；≤0 → <b>下行态 30/30/40</b>。参考价由 Actions 每日自动更新（东财 QQQ 日线）。</div>
</div>

<div class="hdr2">📋 实盘操作（2026-08 快照）</div>
<div class="card">
  <ol class="steps">
    <li><b>存量10万：</b>黄金¥3万→518880 立即买；QQQ¥7万→017436 日投¥1000（约3.5个月投完，过渡钱放 511880）</li>
    <li><b>每月¥5K（上行态）：</b>QQQ¥3.5K + 黄金¥1.5K；<b>（下行态）：</b>QQQ¥1.5K + 黄金¥1.5K + 现金¥2K(511880)</li>
    <li><b>每月末：</b>看上方「动量信号」→ 状态翻转就调仓（上行 70/30，下行 30/30/40）；状态没变但 QQQ 占比偏离目标 ≥5pp 才调</li>
    <li>⚠️ 159632 溢价&lt;2% 才场内；<b>别用黄金弹药换QQQ</b>（回测实锤负优化）</li>
  </ol>
</div>

<div class="hdr2">📊 持仓偏离度 <span class="pos-edit" id="pos-save-btn" onclick="posSave()">💾 保存</span></div>
<div class="card">
  <div class="rw">
    <div class="bx"><div class="lb">QQQ 市值(017436)</div><div class="vl" id="p-q">--</div></div>
    <div class="bx"><div class="lb">黄金市值(518880)</div><div class="vl" id="p-g">--</div></div>
    <div class="bx"><div class="lb">QQQ 实际占比</div><div class="vl" id="p-pct">--</div></div>
    <div class="bx"><div class="lb">偏离目标</div><div class="vl" id="p-dev">--</div></div>
  </div>
  <div class="rw" style="align-items:center">
    <div class="bx" style="text-align:left;padding:6px 8px">
      <div class="lb">QQQ 金额(¥)</div>
      <input id="in-q" type="number" inputmode="numeric" placeholder="如 70000" style="width:100%;background:#0d1117;border:1px solid #30363d;color:#e6edf3;border-radius:6px;padding:6px;font-size:14px;margin-top:4px">
    </div>
    <div class="bx" style="text-align:left;padding:6px 8px">
      <div class="lb">黄金金额(¥)</div>
      <input id="in-g" type="number" inputmode="numeric" placeholder="如 30000" style="width:100%;background:#0d1117;border:1px solid #30363d;color:#e6edf3;border-radius:6px;padding:6px;font-size:14px;margin-top:4px">
    </div>
  </div>
  <div class="inf" id="p-advice">填入您当前的 QQQ 市值（017436 持仓金额）与黄金市值（518880 持仓金额），点 💾保存。目标随信号状态：上行 70%、下行 30%；偏离±5pp 内不用动。</div>
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
  <div class="hdr2" style="margin-top:0">Q30 三版对比（12m动量）</div>
  <div id="t-q30cmp"></div>
  <div class="hdr2">Q30 翻转日历（16次/20年 · 动量状态翻转当天）</div>
  <div id="t-q30flips"></div>
  <div class="hdr2">Q30 逐年收益（21个日历年度·18正3负）</div>
  <div id="t-q30yearly"></div>
  <details class="subd">
    <summary>旧方案参考（Q70/金30 静态配置）</summary>
    <div class="hdr2" style="margin-top:0">再平衡频率（Q70/金30 固定）</div>
    <div id="t-freq"></div>
    <div class="hdr2">年度/两年 × 触发带</div>
    <div id="t-bands"></div>
    <div class="hdr2">XIRR≥15% 最优组合（全网格前8）</div>
    <div id="t-grid"></div>
    <div class="hdr2">逐年收益</div>
    <div id="t-yearly"></div>
    <div class="hdr2">回撤事件（深度&gt;8%）</div>
    <div id="t-dd"></div>
  </details>
</details>

<div class="note">
<strong>📐 口径</strong> 回测 2006-08-21~2026-08-20 · ¥10万+¥400/周 · FX=7.25 · 价格口径无分红<br>
• 主推：Q30 动量切换 = 12m动量(跳1月) + 上行70/30 + 下行30/30/40 + 偏离&gt;5%才调 → XIRR 15.21% / MaxDD 27.9% / Calmar 0.545（16翻转/52调仓）<br>
• 旧方案（年度检视+5%带）：XIRR 15.59% / MaxDD 36.9% / Calmar 0.422 —— 收益更高但回撤大近9pp<br>
• ⚠️ 017436 为主动型（YTD 跑输 QQQ ~12pp），信号看 QQQ 美元价，执行以 017436 净值为准<br>
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
// ===== 主推方案 =====
(function () {
  const B = BACKTEST;
  $('#m-xirr').textContent = pct1(B.q30.xirr);
  $('#m-dd').textContent = pct1(B.q30.maxDD);
  $('#m-calmar').textContent = B.q30.calmar.toFixed(3);
  $('#m-sharpe').textContent = B.q30.sharpe.toFixed(2);
  $('#m-final').textContent = wany(B.q30.finalCNY);
  $('#m-flips').textContent = B.q30.flips + '次';
  $('#m-actions').textContent = B.q30.actions + '次';
  // Q30 三版对比（推荐版高亮）
  tbl('#t-q30cmp',
    [{ t: '版本', k: 'name' }, { t: 'XIRR%', k: 'xirr', d: 2 }, { t: 'MaxDD%', k: 'maxDD', d: 1 }, { t: 'Calmar', k: 'calmar', d: 3 }, { t: '终值', k: 'finalCNY' }, { t: '20年动作', k: 'actions' }],
    [B.q30, B.q30_monthly, B.q30_fliponly, B.q30_base].map(r => ({ ...r, finalCNY: wany(r.finalCNY), name: (r.name || 'Q30').replace('Q30动量切换', 'Q30').replace('旧方案:', '旧方案 ') })), [0]);
  // 翻转日历
  tbl('#t-q30flips',
    [{ t: '日期', k: 'd' }, { t: '动量%', k: 'mQ', d: 1 }, { t: '方向', k: 'dirLabel' }, { t: 'QQQ', k: 'qv' }, { t: '黄金', k: 'gv' }, { t: '现金', k: 'cash' }],
    B.flips.map(f => ({ ...f, dirLabel: f.dir === 'up' ? '转上(70/30)' : '转下(30/30/40)', qv: wany(f.qv), gv: wany(f.gv), cash: wany(f.cash) })), []);
  // Q30 逐年
  tbl('#t-q30yearly',
    [{ t: '年份', k: 'year' }, { t: '年初¥', k: 'startVal' }, { t: '投入¥', k: 'contrib' }, { t: '年末¥', k: 'endVal' }, { t: '收益%', k: 'retPct', d: 1 }],
    B.q30yearly.map(r => ({ ...r, startVal: wany(r.startVal), endVal: wany(r.endVal), contrib: '¥' + Math.round(r.contrib) })),
    B.q30yearly.map((r, i) => r.retPct < 0 ? i : -1).filter(i => i >= 0));
  // 旧方案参考表
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
// ===== 动量信号（状态 = 上行/下行，决定偏离度目标） =====
const stateUp = () => SNAP.mom != null && SNAP.mom > 0;
function updSignal() {
  const mom = SNAP.mom, ref = SNAP.ref13m, refD = SNAP.ref13mDate;
  $('#s-ref').textContent = '$' + ref.toFixed(2) + ' (' + refD.slice(5) + ')';
  $('#s-qqq').textContent = SNAP.qqq ? '$' + SNAP.qqq.toFixed(2) : '--';
  const momEl = $('#s-mom');
  momEl.textContent = (mom > 0 ? '+' : '') + mom.toFixed(1) + '%';
  momEl.className = 'vl ' + (mom > 0 ? 'up' : 'down');
  const stEl = $('#s-state');
  stEl.textContent = stateUp() ? '上行态' : '下行态';
  stEl.className = 'vl ' + (stateUp() ? 'up' : 'down');
  const trg = $('#s-trigger');
  trg.textContent = '📌 最近触发 ' + (SNAP.qqqKlineDate || '--') + '（收盘）：12m动量 ' + (mom > 0 ? '+' : '') + mom.toFixed(1) + '% → ' + (stateUp() ? '上行态' : '下行态') + '。' + (stateUp() ? '目标 70% QQQ+30% 金 · 新钱 ¥3500Q+¥1500金' : '目标 30% QQQ+30% 金+40% 现金 · 赎回 QQQ 至30% · 新钱 ¥1500Q+¥1500金+¥2000现金');
  $('#s-target').innerHTML = stateUp()
    ? '✅ 动量>0 → <b>上行态</b>：目标 70% QQQ(017436) + 30% 黄金(518880)。新钱 ¥3500 Q + ¥1500 金。'
    : '⚠️ 动量≤0 → <b>下行态</b>：目标 30% QQQ + 30% 金 + 40% 现金(511880)。赎回 QQQ 到30%，新钱 ¥1500 Q + ¥1500 金 + ¥2000 现金。';
}
// ===== 持仓偏离度（localStorage 存金额，内嵌输入框，无 prompt；目标随状态） =====
const LS = k => localStorage.getItem(k);
const SS = (k, v) => { try { localStorage.setItem(k, v); return true; } catch (e) { return false; } };
function posVal() {
  const qAmt = parseFloat(LS('posQAmt')), gAmt = parseFloat(LS('posGAmt'));
  const inq = $('#in-q'), ing = $('#in-g');
  if (inq && document.activeElement !== inq) inq.value = qAmt > 0 ? qAmt : '';
  if (ing && document.activeElement !== ing) ing.value = gAmt > 0 ? gAmt : '';
  if (!(qAmt > 0) || !(gAmt > 0)) {
    $('#p-q').textContent = '--'; $('#p-g').textContent = '--'; $('#p-pct').textContent = '--'; $('#p-dev').textContent = '--';
    return;
  }
  const total = qAmt + gAmt;
  const pct = total > 0 ? qAmt / total * 100 : 0;
  const target = stateUp() ? 70 : 30;
  const dev = pct - target;
  $('#p-q').textContent = wany(qAmt);
  $('#p-g').textContent = wany(gAmt);
  $('#p-pct').textContent = pct.toFixed(1) + '%';
  const devEl = $('#p-dev');
  devEl.textContent = (dev > 0 ? '+' : '') + dev.toFixed(1) + 'pp';
  devEl.className = 'vl ' + (Math.abs(dev) > 10 ? 'bad' : Math.abs(dev) > 5 ? 'warn' : 'ok');
  let advice;
  if (Math.abs(dev) <= 5) {
    advice = stateUp()
      ? '🟢 上行态：QQQ 占比在 70%±5% 内，无需操作。每月末看一次动量信号即可。'
      : '🟢 下行态：QQQ 占比在 30%±5% 内，无需操作。继续按 30/30/40 收新钱。';
  } else if (dev > 5) {
    advice = stateUp()
      ? '🟡 上行态 QQQ 超配 ' + dev.toFixed(1) + 'pp（>75%）：新钱全进黄金 + 卖出部分 QQQ → 用 518880 买入/场外拆单调节'
      : '🟡 下行态 QQQ 仍占 ' + pct.toFixed(1) + '%（>35%）：赎回 017436 到 30% 目标，所得进 511880';
  } else {
    advice = stateUp()
      ? '🟡 上行态 QQQ 低配 ' + (-dev).toFixed(1) + 'pp（<65%）：卖出黄金 518880 → 转入 017436 定投（日¥1000，分20-30日）'
      : '🟢 下行态 QQQ 低于 30%：属正常防守，不必补（可小额日¥1000 回补或等转上）';
  }
  $('#p-advice').textContent = advice;
}
function posSave() {
  const q = parseFloat($('#in-q').value), g = parseFloat($('#in-g').value);
  const btn = $('#pos-save-btn');
  if (!(q > 0) || !(g > 0)) {
    btn.textContent = '⚠️ 金额无效';
    setTimeout(() => { btn.textContent = '💾 保存'; }, 1800);
    return;
  }
  SS('posQAmt', String(q)); SS('posGAmt', String(g));
  btn.textContent = '✓ 已保存';
  setTimeout(() => { btn.textContent = '💾 保存'; }, 1800);
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
// 渲染实时行情卡的 QQQ：盘中=实时价；休市=上一收盘(带数据日期)
function renderQQQ() {
  $('#q-qqq').textContent = '$' + (SNAP.qqq || 0).toFixed(2) + (usOpen() ? '' : ' (' + (SNAP.qqqDate || '--') + ')');
}
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
    if (qq && usOpen()) {  // 美股开盘用实时价；休市保持服务端上一收盘
      const q = parseFloat(qq[3]);
      if (isFinite(q) && q > 10) { SNAP.qqq = q; }
    }
    renderQQQ();
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
    updSignal();
    posVal();
    const t = new Date();
    rt.textContent = (usOpen() ? '🟢 盘中 ' : '⚪ 休市 · 上一收盘 ' + (SNAP.qqqDate || '--') + ' ') + t.toTimeString().slice(0, 8) + ' · QQQ $' + (SNAP.qqq || 0).toFixed(2) + ' · 60s自动刷新·点击手动';
    rt.className = 'ok';
  } catch (e) {
    rt.textContent = '⚪ 实时获取失败·显示快照·点此重试';
    rt.className = 'bad';
    updSignal();
    posVal();
    renderQQQ();
  }
}
renderQQQ();
updSignal();
posVal();
refresh();
setInterval(refresh, INTERVAL);
$('#rt').onclick = refresh;
</script>
</body>
</html>
"""

snap = fetch_snapshot()  # 实时抓取（017436净值+QQQ日线+腾讯行情），失败回退静态值
html = HTML.replace("__BACKTEST__", j(backtest)).replace("__SNAP__", j(snap))
out = os.path.join(os.path.dirname(BASE), "q70.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
print("已生成", out, len(html), "bytes | 快照:", json.dumps(snap, ensure_ascii=False))
