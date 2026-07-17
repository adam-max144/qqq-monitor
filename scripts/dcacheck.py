#!/usr/bin/env python3
"""检查今日定投建议并发送邮件"""
import json, urllib.request, smtplib, os
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()

# 1. 获取QQQ数据
raw = fetch("https://qt.gtimg.cn/q=usQQQ")
text = raw.decode("gbk", errors="replace")
import re
m = re.search(r'v_usQQQ="(.*?)"', text)
if not m:
    print("❌ QQQ数据获取失败"); exit(0)
f = m.group(1).split("~")
price = float(f[3]) if f[3] else 0
prev_close = float(f[4]) if f[4] else 0
high52 = float(f[48]) if len(f) > 48 and f[48] else 0
low52 = float(f[49]) if len(f) > 49 and f[49] else 0
name = f[1] if len(f) > 1 else "QQQ"

# 2. 获取VXN
try:
    vxn_raw = fetch("https://adam-max144.github.io/qqq-monitor/vxn.json")
    vxn_data = json.loads(vxn_raw)
    vxn = vxn_data.get("vxn")
    vxn_date = vxn_data.get("date", "?")
except:
    vxn = None
    vxn_date = "?"

# 3. 计算
chg_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0
dd52 = ((high52 - price) / high52 * 100) if high52 > 0 else 0
dd = round(dd52, 1)

# 4. 判断档位
tiers = [
    (0, "平静区", 0, 0),
    (1, "小幅回调", 0.5, 5),
    (2, "中度回调", 1.0, 10),
    (3, "恐慌性回调", 1.5, 18),
    (4, "深度熊市", 2.0, 23),
    (5, "史诗级崩盘", 2.5, 28),
]

tier = 0
mult = 0
if vxn is not None and vxn >= 24:
    for t_id, t_label, t_mult, t_dd in reversed(tiers):
        if t_id > 0 and dd >= t_dd:
            tier = t_id
            mult = t_mult
            break

# 5. 趋势判断
pos = ((price - low52) / (high52 - low52) * 100) if high52 > low52 else 50
is_bull = pos > 71
is_bear = pos < 33

if is_bull and tier >= 3:
    mult = min(mult, 2.0)

# 6. 构建消息
vxn_str = f"VXN={vxn}({vxn_date})" if vxn else "VXN=N/A"
action = f"加仓{mult}×" if tier > 0 else "正常定投"
extra_str = f"(+¥{round(400*mult)})" if tier > 0 else ""
trend_str = "牛市" if is_bull else ("熊市" if is_bear else "中性")
today = datetime.now().strftime("%Y-%m-%d")

total = 400 + (round(400*mult) if tier > 0 else 0)

subject = f"📅 QQQ定投建议 | {today}"
body = f"""
━━━ QQQ 定投策略 · 今日建议 ━━━

日期: {today}
QQQ: ${price:.2f}  ({chg_pct:+.2f}%)
{vxn_str} | 回撤={dd}% | 52周位={pos:.0f}%({trend_str})

档位: T{tier} {tiers[tier][1]}
操作: {action} {extra_str}
建议投入: ¥{total}
"""

if is_bull and tier >= 3:
    body += "⚠️ 牛市高位区，加仓上限2×\n"
if dd > 10:
    body += "⚡ 注意: 回撤较深，注意风险\n"

body += "\n━━━━━━━━━━━━━━━━━━━\nhttps://adam-max144.github.io/qqq-monitor/\n"

print(body)

# 7. 发送邮件
try:
    smtp_user = "941189835@qq.com"
    smtp_pass = "ualqcpqiekupbdej"
    smtp_host = "smtp.qq.com"
    smtp_port = 465

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = smtp_user
    msg["To"] = smtp_user

    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [smtp_user], msg.as_string())

    print("✅ 邮件已发送到 941189835@qq.com")
except Exception as e:
    print(f"❌ 邮件发送失败: {e}")
