# -*- coding: utf-8 -*-
"""溢价窗口提醒 —— 场内纳指ETF「真实溢价」跌破阈值时推送(邮件; ntfy 已于 2026-09-12 关停)

口径与 monitor.html 浏览器实时层完全一致(单一事实源):
  1) 从线上 monitor.html 取内嵌 FUND_META(净值/净值日/QQQ基准/是否纳指100)
  2) 腾讯行情取现价 + QQQ 最新「已收盘」价(同页面 usPhase/qqqLast 逻辑)
  3) 真实溢价 = 现价 / (净值 × (1 + QQQ最新/QQQ基准 - 1)) - 1
  4) 任一"纯纳指100"(win=true) 标的真实溢价 < 阈值 → 推送

环境变量:
  MAIL_TO / SMTP_USER / SMTP_PASS  邮件渠道(缺任一则跳过该渠道, 且不算失败)
  NTFY_TOPIC  可选, 留空则不发 ntfy(现役配置为空)
  THRESHOLD   可选, 默认 2 (%); workflow_dispatch 可传入做端到端测试
  PAGE_URL    可选, 默认线上 Pages 地址

退出码: 0 正常(含未触发); 1 取数失败; 2 推送失败
"""
import json, os, re, smtplib, ssl, sys
from datetime import datetime
from email.message import EmailMessage
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


def us_phase(now_et):
    """美股阶段: open 盘中(9:30-16:00) / pre 盘前(4:00-9:30) / settled 收盘后·凌晨·周末"""
    h = now_et.hour + now_et.minute / 60
    wd = now_et.weekday()
    if wd < 5 and 9.5 <= h < 16:
        return "open"
    if wd < 5 and 4 <= h < 9.5:
        return "pre"
    return "settled"


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
    # ⚠️ 腾讯 p[4]「昨收」= 最新收盘的**前一交易日**收盘: 只有盘前(p[3] 是盘前成交价)才该用它;
    #    10:40 检查时美股恒为「收盘后」, 若取 p[4] 会整体少算一天美股涨跌 → 溢价虚高 ~2pp(恰是触发线)。
    phase = us_phase(now_et)
    qqq_live = float(qqq[4] if phase == "pre" else qqq[3])
    print(f"QQQ = {qqq_live}  ({'盘中' if phase == 'open' else '盘前·取上日收盘' if phase == 'pre' else '休市·取最新收盘'})  阈值 {THRESHOLD}%  北京 {datetime.now(ZoneInfo('Asia/Shanghai')):%m-%d %H:%M}")

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

    results = {}
    if TOPIC:
        results["ntfy"] = send_ntfy(title, body)
    if os.environ.get("MAIL_TO", "").strip():
        results["mail"] = send_mail(title, body)
    if not results:
        print("未配置任何推送渠道(NTFY_TOPIC / MAIL_TO), 只打印不推送")
        return 0
    for k, v in results.items():
        print(f"  {k}: {v}")
    # 只有真正发失败才算失败; skip(未配置)不算 —— 否则缺凭据时 CI 会天天标红
    return 2 if any(str(v).startswith("fail") for v in results.values()) else 0


def send_ntfy(title, body):
    """走 JSON 接口 —— HTTP 头是 latin-1, 中文/emoji 标题用头会抛 UnicodeEncodeError"""
    try:
        r = requests.post("https://ntfy.sh/", timeout=20, json={
            "topic": TOPIC, "title": title, "message": body,
            "priority": 4, "tags": ["moneybag"], "click": PAGE_URL,
        })
        return "ok" if r.status_code == 200 else f"fail({r.status_code})"
    except Exception as e:
        return f"fail({type(e).__name__}: {str(e)[:60]})"


def send_mail(title, body):
    """SMTP 发邮件(默认 QQ 邮箱 smtp.qq.com:465 SSL; 密码填**授权码**, 不是登录密码)"""
    host = os.environ.get("SMTP_HOST", "smtp.qq.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ.get("SMTP_USER", "").strip()
    pwd = os.environ.get("SMTP_PASS", "").strip()
    to = os.environ.get("MAIL_TO", "").strip()
    if not (user and pwd):
        missing = " + ".join(n for n, v in (("SMTP_USER", user), ("SMTP_PASS", pwd)) if not v)
        return f"skip(缺 {missing})"
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = title
    msg.set_content(f"{title}\n\n{body}\n\n页面: {PAGE_URL}\n(由 GitHub Actions 每日自检自动发出)")
    try:
        auth = os.environ.get("SMTP_AUTH", "1") != "0"      # 0 = 无认证中继(本地联调/自建中继用)
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=25, context=ssl.create_default_context()) as s:
                if auth:
                    s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=25) as s:
                if os.environ.get("SMTP_TLS", "1") != "0":
                    s.starttls(context=ssl.create_default_context())
                if auth:
                    s.login(user, pwd)
                s.send_message(msg)
        return "ok"
    except Exception as e:
        return f"fail({type(e).__name__}: {str(e)[:80]})"


if __name__ == "__main__":
    sys.exit(main())
