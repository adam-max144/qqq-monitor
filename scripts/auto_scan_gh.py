"""基金自动扫描脚本（GitHub Actions版）"""
import urllib.request, json, base64, re, os
from datetime import datetime

LIMIT_MIN = 1000
OWNER = "adam-max144"
REPO = "qqq-monitor"

KNOWN_DATA = {
    "005698": {"limit": 5000, "tech": 80, "type": "A", "fee": "0.12%", "rate": "S", "note": "华夏全球科技先锋A"},
    "024239": {"limit": 5000, "tech": 80, "type": "C", "fee": "0%", "rate": "S", "note": "华夏全球科技先锋C"},
    "017653": {"limit": 100000, "tech": 85, "type": "A", "fee": "0.12%", "rate": "A", "note": "创金合信全球芯片A"},
    "017436": {"limit": 1000, "tech": 95, "type": "A", "fee": "0.12%", "rate": "A", "note": "华宝纳斯达克精选A"},
    "017437": {"limit": 1000, "tech": 95, "type": "C", "fee": "0%", "rate": "A", "note": "华宝纳斯达克精选C"},
    "017730": {"limit": 1000, "tech": 80, "type": "A", "fee": "0.12%", "rate": "B", "note": "嘉实全球产业升级A"},
    "017731": {"limit": 1000, "tech": 80, "type": "C", "fee": "0%", "rate": "B", "note": "嘉实全球产业升级C"},
    "100055": {"limit": 1000, "tech": 60, "type": "A", "fee": "0.12%", "rate": "B", "note": "富国全球科技互联A"},
    "022184": {"limit": 1000, "tech": 60, "type": "C", "fee": "0%", "rate": "B", "note": "富国全球科技互联C"},
    "000041": {"limit": 10000, "tech": 40, "type": "A", "fee": "0.12%", "rate": "C", "note": "华夏全球股票"},
    "018229": {"limit": 1000, "tech": 40, "type": "A", "fee": "0.12%", "rate": "C", "note": "易方达全球优质企业A"},
    "018230": {"limit": 1000, "tech": 40, "type": "C", "fee": "0%", "rate": "C", "note": "易方达全球优质企业C"},
    "006308": {"limit": 1000, "tech": 30, "type": "A", "fee": "0.12%", "rate": "D", "note": "汇添富全球消费A"},
    "006309": {"limit": 1000, "tech": 30, "type": "C", "fee": "0%", "rate": "D", "note": "汇添富全球消费C"},
}

def check_limit(code):
    try:
        url = f"http://fundf10.eastmoney.com/jjgg_{code}_4.html"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://fund.eastmoney.com/"})
        html = urllib.request.urlopen(req, timeout=10).read().decode("gbk", "ignore")
        m = re.search(r"单日累计购买上限(\d+)([元百千万])", html)
        if m:
            num, unit = int(m.group(1)), m.group(2)
            if unit == "百": num *= 100
            elif unit == "千": num *= 1000
            elif unit == "万": num *= 10000
            elif unit == "十": num *= 10
            return num
        if "暂停申购" in html: return 0
        if "最高超" in html or re.search(r"限额[^。]*超", html): return 99999
    except:
        pass
    return -1

qualify = []
now = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
print(f"扫描时间: {now}")

for code, kd in sorted(KNOWN_DATA.items()):
    live = check_limit(code)
    limit = live if live >= 0 else kd["limit"]
    if live >= 0 and live != kd["limit"]:
        print(f"  ⚠️ {code} 限购变化: ¥{kd['limit']:,} → ¥{live:,}")

    if limit >= LIMIT_MIN:
        sub = f"{kd['type']}类 · 科技占比~{kd['tech']}% · {kd['note']}"
        if limit >= 5000: sub += " · ✅ 额度充裕"
        elif limit >= 2000: sub += " · ✅ 额度充足"
        qualify.append({"code": code, "limit": limit, "tech": kd["tech"],
                        "fee": kd["fee"], "type": kd["type"], "sub": sub, "rate": kd["rate"]})

qualify.sort(key=lambda x: ("SABCD".index(x["rate"]), -x["tech"]))
print(f"符合条件: {len(qualify)}只")

rows = ""
for f in qualify:
    lt = f"¥{f['limit']:,}/天" if f["limit"] < 99999 else "无限购"
    lc = "ok" if f["limit"] >= 2000 else "warn"
    rows += f"""
    <div class="fund">
      <div class="hdr"><b>{KNOWN_DATA[f['code']]['note']}</b><span class="cd">{f['code']}</span></div>
      <div class="rw">
        <div class="bx"><div class="lb">限购</div><div class="vl {lc}">{lt}</div></div>
        <div class="bx"><div class="lb">科技占比</div><div class="vl ok">~{f['tech']}%</div></div>
        <div class="bx"><div class="lb">申购费</div><div class="vl">{f['fee']}</div></div>
        <div class="bx"><div class="lb">类型</div><div class="vl">{f['type']}类</div></div>
      </div>
      <div class="inf"><span class="rate-{f['rate']}">{f['rate']}</span> · {f['sub']}</div>
    </div>"""

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>美股科技基金 · 自动筛选</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,sans-serif;background:#0d1117;color:#e6edf3;padding:16px;max-width:500px;margin:0 auto}}
h1{{font-size:20px;font-weight:700}}
.sub{{font-size:11px;color:#8b949e;margin:4px 0 14px}}
.fund{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:14px;margin-bottom:10px}}
.hdr{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}}
.hdr b{{font-size:14px}}
.cd{{font-size:10px;color:#8b949e;background:#21262d;padding:2px 6px;border-radius:4px}}
.rw{{display:flex;gap:6px}}
.bx{{flex:1;padding:6px 4px;border-radius:6px;text-align:center;background:#0d1117;border:1px solid #21262d}}
.bx .lb{{color:#8b949e;font-size:9px}}
.bx .vl{{font-weight:700;font-size:13px;margin-top:2px}}
.ok{{color:#3fb950}} .warn{{color:#d29922}}
.inf{{font-size:10px;color:#8b949e;margin-top:6px}}
em{{color:#8b949e;display:block;text-align:center;padding:20px;font-size:13px}}
.note{{margin-top:14px;padding:10px;background:#1c2128;border-radius:8px;font-size:10px;color:#8b949e;line-height:1.6;border:1px solid #21262d}}
.rate-S{{display:inline-block;background:#002d1a;color:#3fb950;padding:1px 6px;border-radius:4px;font-weight:700;font-size:10px}}
.rate-A{{display:inline-block;background:#001a3d;color:#58a6ff;padding:1px 6px;border-radius:4px;font-weight:700;font-size:10px}}
.rate-B{{display:inline-block;background:#3d3200;color:#d29922;padding:1px 6px;border-radius:4px;font-weight:700;font-size:10px}}
.rate-C{{display:inline-block;background:#1c2128;color:#8b949e;padding:1px 6px;border-radius:4px;font-weight:700;font-size:10px}}
.rate-D{{display:inline-block;background:#3d0000;color:#f85149;padding:1px 6px;border-radius:4px;font-weight:700;font-size:10px}}
</style>
</head>
<body>
<h1>📡 美股科技基金监控</h1>
<p class="sub">{now} · 共{len(qualify)}只 · GitHub Actions自动更新</p>
<div id="list">{rows}</div>
<div class="note"><strong>⏱ 自动更新</strong><br>• 每天UTC 1:00（北京9:00）由GitHub Actions扫描<br>• 扫描QDII基金 → 筛选美股科技+限购&gt;¥1,000</div>
</body>
</html>'''

with open("monitor.html", "w", encoding="utf-8") as f:
    f.write(html)
print("✅ monitor.html 已生成")
