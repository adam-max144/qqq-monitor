# -*- coding: utf-8 -*-
"""溢价窗口提醒 —— 场内纳指ETF「真实溢价」跌破阈值时用 ntfy 推到手机

口径与 monitor.html 浏览器实时层完全一致(单一事实源):
  1) 从线上 monitor.html 取内嵌 FUND_META(净值/净值日/QQQ基准/是否纳指100)
  2) 腾讯行情取现价 + QQQ 最新收盘(休市用昨收, 同页面 usOpen 逻辑)
  3) 真实溢价 = 现价 / (净值 × (1 + QQQ最新/QQQ基准 - 1)) - 1
  4) 任一"纯纳指100"(win=true) 标的真实溢价 < 阈值 → 推送

环境变量:
  NTFY_TOPIC  必填(缺失则只打印不发), 例如 qqq-premium-xxxx
  THRESHOLD   可选, 默认 2 (%); workflow_dispatch 可传入做端到端测试
  PAGE_URL    可选, 默认线上 Pages 地址

退出码: 0 正常(含未触发); 1 取数失败; 2 推送失败
"""
import json, os, re, sys
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

PAGE_URL = os.environ.get("PAGE_URL", "https://adam-max144.github.io/qqq-monitor/monitor.html")
TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
THRESHOLD = float(os.environ.get("THRESHOLD", "2") or 2)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch_meta():
    """从生成好的页面里取 FUND_META —— 与页面同源, 不另立一套净值口径"""
    html = requests.get(PAGE_URL, headers=UA, timeout=30).text
    m = re.search(r"const FUND_META = (\{.*?\});const POSITION_META", html, re.DOTALL)
    if not m:
        raise SystemExit("未能从页面解析 FUND_META(页面结构可能已变)")
    return json.loads(m.group(1))


def us_open(now_et):
    return now_et.weekday() < 5 and 9.5 <= now_et.hour + now_et.minute / 60 < 16


def fetch_quotes(codes):
    syms = ",".join(("sh" if c.startswith(("5", "6")) else "sz") + c for c in codes) + ",usQQQ"
    raw = requests.get("https://qt.gtimg.cn/q=" + syms, headers={**UA, "Referer": "https://gu.qq.com/"},
                       timeout=25).content.decode("gbk", "replace")
    rows = {}
    for seg in raw.split(";"):
        m = re.search(r'v_([A-Za-z0-9.]+)="([^"]*)"', seg)
        if m:
            p = m.group(2).split("~")
            if len(p) > 40:
                rows[p[2]] = p
    return rows


def main():
    meta = fetch_meta()
    now_et = datetime.now(ZoneInfo("America/New_York"))
    rows = fetch_quotes(list(meta.keys()))
    qqq = next((v for k, v in rows.items() if k.startswith("QQQ.")), None) or rows.get("QQQ")
    if not qqq:
        print("QQQ 行情缺失"); return 1
    qqq_live = float(qqq[3] if us_open(now_et) else qqq[4])
    print(f"QQQ = {qqq_live}  ({'盘中' if us_open(now_et) else '休市·取昨收'})  阈值 {THRESHOLD}%  北京 {datetime.now(ZoneInfo('Asia/Shanghai')):%m-%d %H:%M}")

    hits, lines = [], []
    for code, f in meta.items():
        p = rows.get(code)
        if not p:
            lines.append(f"  {code:8s} 无行情"); continue
        price = float(p[3])
        nav, base = f.get("nav"), f.get("qqqBase")
        if not nav or not base or price <= 0:
            lines.append(f"  {code:8s} 缺净值/基准, 跳过"); continue
        premt = (price / (nav * (1 + qqq_live / base - 1)) - 1) * 100
        flag = "★纳指100" if f.get("win") else "  参考  "
        lines.append(f"  {code:8s} {flag} 现价 {price:>7.3f} 净值 {nav} 真实溢价 {premt:6.2f}%")
        if f.get("win") and premt < THRESHOLD:
            hits.append((code, f.get("name", code), premt))
    print("\n".join(lines))

    if not hits:
        print(f"\n未触发: 无纯纳指100标的真实溢价 < {THRESHOLD}%")
        return 0

    hits.sort(key=lambda x: x[2])
    txt = " / ".join(f"{n} {v:.2f}%" for _, n, v in hits)
    title = f"🟢 溢价窗口开启({len(hits)}只<{THRESHOLD:g}%)"
    body = f"{txt}\n现价已回到成本线附近 → 可用蓄水池/弹药买入场内纳指\n(触发线 <2%, 数据源: 页面快照净值+QQQ实时校正)"
    print(f"\n触发推送: {title} | {body.splitlines()[0]}")
    if not TOPIC:
        print("未配置 NTFY_TOPIC, 只打印不推送")
        return 0
    r = requests.post("https://ntfy.sh/", timeout=20, json={
        "topic": TOPIC, "title": title, "message": body,
        "priority": 4, "tags": ["moneybag"], "click": PAGE_URL,
    })   # ⚠️ 必须走 JSON 接口: HTTP 头是 latin-1, 中文/emoji 标题会在 http.client 里直接抛 UnicodeEncodeError
    print("推送结果:", r.status_code, r.json().get("id"))
    return 0 if r.status_code == 200 else 2


if __name__ == "__main__":
    sys.exit(main())
