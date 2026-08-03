"""场内纳指基金自动扫描脚本（GitHub Actions版）
数据源（全部实测可用，无第三方依赖）:
- 腾讯批量行情 qt.gtimg.cn: 现价/昨收/成交额/总市值/名称
- 天天基金 pingzhongdata: 官方单位净值序列 + 净值日（QDII净值滞后T+2）
- 新浪美股日K: QQQ/SPY 收盘，用于把披露溢价校正为真实溢价
- 费用/成立/经理: 静态配置（2026-08-03 从天天基金App接口逐只验证）
输出: monitor.html（场内纳指基金监控页）
"""
import urllib.request, json, re, time
from datetime import datetime

# 监控标的（场内QDII ETF，全部纯美股指数、无A股；仅保留纳斯达克100）
# code: [市场 sh/sz, 指数类别, 管理费%, 托管费%, 是否核心推荐, 备注]
FUNDS = {
    "159632": ["sz", "纳指100", 0.60, 0.20, True,  "⭐主力·当前溢价最低的大规模纳指"],
    "513300": ["sh", "纳指100", 0.60, 0.20, True,  "⭐主力·规模/流动性/品牌最佳"],
    "513100": ["sh", "纳指100", 0.60, 0.20, False, "老牌最大·溢价全场最贵"],
    "159941": ["sz", "纳指100", 0.80, 0.20, False, "规模最大·溢价最贵"],
    "513110": ["sh", "纳指100", 0.80, 0.20, False, "溢价低·费率偏高"],
    "513390": ["sh", "纳指100", 0.50, 0.15, False, "费率最低"],
    "159659": ["sz", "纳指100", 0.50, 0.15, False, ""],
    "159696": ["sz", "纳指100", 0.50, 0.10, False, "费率最低档"],
    "159501": ["sz", "纳指100", 0.50, 0.10, False, ""],
    "513870": ["sh", "纳指100", 0.50, 0.10, False, ""],
}
INDEX_US = {"纳指100": "QQQ"}  # 真实溢价校正用

def fetch(url, ref, tries=3, enc="utf-8"):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": ref})
            return urllib.request.urlopen(req, timeout=20).read().decode(enc, "ignore")
        except Exception as e:
            last = e
            time.sleep(1.0 * (i + 1))
    raise last

# ---------- 1. 腾讯批量行情 ----------
def fetch_quotes():
    syms = ",".join(("sh" if m == "sh" else "sz") + c for c, m in
                    ((c, FUNDS[c][0]) for c in FUNDS))
    raw = fetch("https://qt.gtimg.cn/q=" + syms, "https://gu.qq.com/", enc="gbk")
    out = {}
    for line in raw.strip().split(";"):
        line = line.strip()
        if "=" not in line or "~" not in line:
            continue
        p = line.split("~")
        if len(p) < 60:
            continue
        code = p[2]
        try:
            out[code] = {
                "name": p[1].replace("ETF", "ETF"),
                "price": float(p[3]),
                "prev": float(p[4]),
                "amount_yi": float(p[37]) / 10000.0,   # 成交额(万)->亿
                "mcap_yi": float(p[45]),               # 总市值(亿)
            }
        except (ValueError, IndexError):
            continue
    return out

# ---------- 2. 天天基金净值序列 ----------
def fetch_nav(code):
    raw = fetch(f"https://fund.eastmoney.com/pingzhongdata/{code}.js",
                "https://fund.eastmoney.com/")
    m = re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", raw, re.DOTALL)
    if not m:
        return {}, None, None
    trend = json.loads(m.group(1))
    nav_map = {}
    for p in trend:
        d = datetime.utcfromtimestamp(p["x"] / 1000).strftime("%Y-%m-%d")
        nav_map[d] = p["y"]
    dates = sorted(nav_map.keys())
    return nav_map, dates[-1] if dates else None, nav_map[dates[-1]] if dates else None

# ---------- 3. 腾讯日K（场内价，算近期涨跌和20日均溢价） ----------
def fetch_kline(sym):
    raw = fetch(f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,45,qfq",
                "https://gu.qq.com/")
    d = json.loads(raw)
    k = d["data"][sym]
    days = k.get("qfqday") or k.get("day") or []
    return {row[0]: float(row[2]) for row in days}

# ---------- 4. 美股日K（QQQ/SPY 校正） ----------
def fetch_us_kline(sym):
    url = (f"https://stock.finance.sina.com.cn/usstock/api/jsonp_v2.php/"
           f"var%20_{sym}_=/US_MinKService.getDailyK?symbol={sym}&___qn=30")
    raw = fetch(url, "https://finance.sina.com.cn/")
    m = re.search(r"\((.*)\)", raw, re.DOTALL)
    if not m:
        return {}
    data = json.loads(m.group(1))
    return {row["d"]: float(row["c"]) for row in data if isinstance(row, dict) and "d" in row}

# ---------- 主流程 ----------
quotes = fetch_quotes()
print(f"行情获取: {len(quotes)}/{len(FUNDS)} 只")

us_closes = {idx: fetch_us_kline(sym) for idx, sym in INDEX_US.items()}

results = []
for code, (market, index, mgmt, trust, core, note) in FUNDS.items():
    rec = {"code": code, "market": market, "index": index, "mgmt": mgmt, "trust": trust,
           "core": core, "note": note, "ok": False}
    try:
        q = quotes.get(code)
        if not q:
            print(f"  ⚠️ {code} 无行情")
            results.append(rec)
            continue
        nav_map, nav_date, nav_last = fetch_nav(code)
        kline = fetch_kline(market + code)
        rec["name"] = q["name"]
        rec["price"] = q["price"]
        rec["prev"] = q["prev"]
        rec["chg_pct"] = (q["price"] / q["prev"] - 1) * 100 if q["prev"] else None
        rec["amount_yi"] = q["amount_yi"]
        rec["mcap_yi"] = q["mcap_yi"]

        # 近5日涨跌
        dates5 = sorted(kline.keys())
        if len(dates5) >= 6 and dates5[-6] in kline:
            rec["chg5_pct"] = (q["price"] / kline[dates5[-6]] - 1) * 100
        else:
            rec["chg5_pct"] = None

        # 披露溢价（官方净值口径，含T+2滞后）
        if nav_last:
            rec["nav_date"] = nav_date
            rec["nav"] = nav_last
            rec["prem_pct"] = (q["price"] / nav_last - 1) * 100
        else:
            rec["prem_pct"] = None

        # 真实溢价 = 现价/(净值 × (1 + 美股区间涨幅)) - 1，区间 = 净值日→美股最新交易日
        if nav_date and nav_date in us_closes.get(index, {}):
            us = us_closes[index]
            us_dates = sorted(us.keys())
            last_us_date = us_dates[-1]
            if last_us_date > nav_date and nav_date in us:
                chg_us = us[last_us_date] / us[nav_date] - 1
                rec["prem_true_pct"] = (q["price"] / (nav_last * (1 + chg_us)) - 1) * 100
                rec["us_chg"] = chg_us * 100
                rec["us_note"] = f"{nav_date}→{last_us_date} {chg_us*100:+.1f}%"
        if "prem_true_pct" not in rec:
            rec["prem_true_pct"] = rec["prem_pct"]
            rec["us_note"] = "未校正"

        # 20日均溢价（price/NAV 同日对齐，取最近20个有数据的交易日）
        prems = []
        for date in sorted(kline.keys())[-25:]:
            if date in nav_map:
                prems.append((kline[date] / nav_map[date] - 1) * 100)
        rec["prem20"] = (sum(prems[-20:]) / len(prems[-20:])) if prems else None
        rec["ok"] = True
    except Exception as e:
        print(f"  ⚠️ {code} 处理失败: {e}")
    results.append(rec)
    time.sleep(0.15)

# 排序：核心推荐在前，其余按真实溢价升序
cores = [r for r in results if r["core"]]
others = [r for r in results if not r["core"]]
others.sort(key=lambda r: (r.get("prem_true_pct") if r.get("prem_true_pct") is not None else 999))
results_sorted = cores + others

def pct_str(v, nd=2, sign=False):
    if v is None:
        return "--"
    s = f"{v:+.{nd}f}%" if sign else f"{v:.{nd}f}%"
    return s

def color_prem(v):
    if v is None:
        return "flat"
    if v < 5:
        return "ok"
    if v <= 8:
        return "warn"
    return "bad"

def chg_cls(v):
    if v is None:
        return "flat"
    if v > 0.05:
        return "up"
    if v < -0.05:
        return "down"
    return "flat"

def card(r):
    prem_c = color_prem(r.get("prem_pct"))
    fee = f"{r['mgmt']:.2f}%+{r['trust']:.2f}%"
    lines = f"""
    <div class="fund{' core' if r['core'] else ''}">
      <div class="hdr"><b>{r.get('name','?')}</b>
        <span><span class="cd">{r['code']}</span><span class="tag idx">{r['index']}</span>{'<span class="tag core">核心</span>' if r['core'] else ''}</span>
      </div>
      <div class="rw">
        <div class="bx"><div class="lb">现价</div><div class="vl">{r.get('price','--')}</div></div>
        <div class="bx"><div class="lb">今日涨跌</div><div class="vl {chg_cls(r.get('chg_pct'))}">{pct_str(r.get('chg_pct'), sign=True)}</div></div>
        <div class="bx"><div class="lb">披露溢价</div><div class="vl {prem_c}">{pct_str(r.get('prem_pct'))}</div></div>
        <div class="bx"><div class="lb">真实溢价</div><div class="vl {prem_c}">{pct_str(r.get('prem_true_pct'))}</div></div>
      </div>
      <div class="rw">
        <div class="bx"><div class="lb">近5日</div><div class="vl {chg_cls(r.get('chg5_pct'))}">{pct_str(r.get('chg5_pct'), sign=True)}</div></div>
        <div class="bx"><div class="lb">费用(管理+托管)</div><div class="vl">{fee}</div></div>
        <div class="bx"><div class="lb">规模</div><div class="vl">{r.get('mcap_yi','--')}亿</div></div>
        <div class="bx"><div class="lb">日成交</div><div class="vl">{f"{r['amount_yi']:.2f}" if r.get('amount_yi') is not None else '--'}亿</div></div>
      </div>
      <div class="inf">20日均溢价 <b>{pct_str(r.get('prem20'))}</b> · 净值日 {r.get('nav_date','--')} · 真实溢价校正 {r.get('us_note','')} · {r.get('note','')}</div>
    </div>"""
    return lines

now = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
ok_n = sum(1 for r in results if r["ok"])

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>场内纳指基金监控</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,sans-serif;background:#0d1117;color:#e6edf3;padding:16px;max-width:500px;margin:0 auto}}
h1{{font-size:20px;font-weight:700}}
.sub{{font-size:11px;color:#8b949e;margin:4px 0 14px}}
.fund{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:14px;margin-bottom:10px}}
.fund.core{{border-color:#238636;background:linear-gradient(135deg,#12221a,#161b22)}}
.hdr{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:6px}}
.hdr b{{font-size:13px;line-height:1.4}}
.hdr span{{display:flex;align-items:center;gap:4px;flex-shrink:0}}
.cd{{font-size:10px;color:#8b949e;background:#21262d;padding:2px 6px;border-radius:4px}}
.tag{{font-size:9px;padding:2px 5px;border-radius:4px;font-weight:700}}
.tag.idx{{background:#001a3d;color:#58a6ff}}
.tag.core{{background:#002d1a;color:#3fb950}}
.rw{{display:flex;gap:6px;margin-top:6px}}
.bx{{flex:1;padding:6px 4px;border-radius:6px;text-align:center;background:#0d1117;border:1px solid #21262d;min-width:0}}
.bx .lb{{color:#8b949e;font-size:9px}}
.bx .vl{{font-weight:700;font-size:12px;margin-top:2px;white-space:nowrap}}
.ok{{color:#3fb950}} .warn{{color:#d29922}} .bad{{color:#f85149}} .flat{{color:#8b949e}}
.up{{color:#3fb950}} .down{{color:#f85149}}
.inf{{font-size:10px;color:#8b949e;margin-top:6px;line-height:1.5}}
.hdr2{{font-size:13px;font-weight:700;margin:14px 0 6px;padding:6px 0;border-bottom:1px solid #21262d}}
.note{{margin-top:14px;padding:10px;background:#1c2128;border-radius:8px;font-size:10px;color:#8b949e;line-height:1.6;border:1px solid #21262d}}
</style>
</head>
<body>
<h1>📡 场内纳指基金监控</h1>
<p class="sub">{now} · 共{ok_n}/{len(FUNDS)}只 · 腾讯行情+官方净值 · GitHub Actions自动更新</p>
<div class="hdr2">⭐ 核心推荐</div>
<div id="list">{''.join(card(r) for r in cores if r.get('ok'))}</div>
<div class="hdr2">📋 全部场内纳斯达克100 ETF（按真实溢价升序）</div>
{''.join(card(r) for r in results_sorted)}
<div class="note">
<strong>📐 口径说明</strong><br>
• <b>披露溢价</b> = 现价/最新官方净值 - 1（QDII净值滞后T+2，会偏高）<br>
• <b>真实溢价</b> = 现价/(净值×(1+美股区间涨幅)) - 1，用QQQ/SPY把净值日→最新交易日的美股涨幅扣除<br>
• <b>20日均溢价</b> = 近20个交易日 场内价/同日净值 均值，判断当前贵不贵<br>
• 费用 = 管理费+托管费（静态配置，2026-08-03从天天基金App逐只核实）<br>
• 场内ETF无申购限额，但溢价是隐性成本：&lt;5%可买，5-8%谨慎，&gt;8%建议等回落或换标的<br>
• ⚠️ 若QDII额度恢复、限购解除，溢价会快速收敛，高溢价买入部分将直接受损
</div>
</body>
</html>"""

with open("monitor.html", "w", encoding="utf-8") as f:
    f.write(html)
print(f"✅ monitor.html 已生成（{ok_n}只成功）")
