#!/usr/bin/env python3
"""GitHub Actions: DCA定投日检查 + QQ邮件推送
匹配当前网站策略（方案C: 高位禁T1/T2加仓）"""
import json, urllib.request, smtplib, os, re
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()

def bytes_to_str(buf):
    """GBK解码（兼容Tencent API的GBK编码）"""
    return buf.decode("gbk", errors="replace")

# ===== 1. 获取QQQ实时行情 =====
raw = fetch("https://qt.gtimg.cn/q=usQQQ")
text = bytes_to_str(raw)
m = re.search(r'v_usQQQ="(.*?)"', text)
if not m:
    print("❌ QQQ数据获取失败"); exit(0)
f = m.group(1).split("~")
price = float(f[3]) if f[3] else 0
prev_close = float(f[4]) if f[4] else 0
high52 = float(f[48]) if len(f) > 48 and f[48] else 0
low52 = float(f[49]) if len(f) > 49 and f[49] else 0

# ===== 2. 获取VXN =====
try:
    vxn_raw = fetch("https://adam-max144.github.io/qqq-monitor/vxn.json")
    vxn_data = json.loads(vxn_raw)
    vxn = vxn_data.get("vxn")
    vxn_date = vxn_data.get("date", "?")
    vxn_real = True
except:
    vxn = None
    vxn_date = "?"
    vxn_real = False

# ===== 3. 计算回撤和52周位置 =====
chg_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0
dd52 = ((high52 - price) / high52 * 100) if high52 > 0 else 0
pos = ((price - low52) / (high52 - low52) * 100) if high52 > low52 else 50
dd = round(dd52, 1)

# ===== 4. 策略参数（匹配网站） =====
BASE = 1400  # 用户设置的每周基础
TIERS = [
    (0, "平静区", 0.0, 0),
    (1, "小幅回调", 1.0, 5),
    (2, "中度回调", 2.0, 15),
    (3, "恐慌性回调", 4.0, 22),
    (4, "深度熊市", 6.0, 28),
    (5, "史诗级崩盘", 10.0, 35),
]
VXN_THRESHOLDS = {0: 0, 1: 0, 2: 27, 3: 34, 4: 40, 5: 45}

# ===== 5. 判断档位 =====
tier = 0
mult = 0.0
if vxn is not None and vxn >= 24:
    for t_id, t_label, t_mult, t_dd in reversed(TIERS):
        if t_id > 0:
            vxn_req = VXN_THRESHOLDS[t_id]
            if vxn >= vxn_req and dd >= t_dd:
                tier = t_id
                mult = t_mult
                break

tier_name = TIERS[tier][1] if tier <= 5 else "未知"

# ===== 6. 基础金额计算 =====
base = BASE
# 平静区存钱
if dd < 3:
    base = max(100, round(base / 3))
elif dd < 5:
    base = max(150, round(base / 2))
# 暴跌扩倍
if dd >= 35:
    base = round(base * 3)
elif dd >= 28:
    base = round(base * 1.5)

# 趋势裁剪 + 方案C: 高位禁T1/T2
is_bull = pos > 75
trend_cut_applied = False
suppress_extra = False
if is_bull:
    base = round(base * 0.7)
    trend_cut_applied = True
    if 1 <= tier <= 2:
        suppress_extra = True

# 额外加仓
extra = 0 if (tier == 0 or suppress_extra) else round(base * mult)
total = base + extra

# ===== 7. 趋势描述 =====
if pos > 75:
    trend_label = "📈 牛市高位"
    trend_detail = "禁T1/T2加仓" if suppress_extra else "上限2×"
elif pos < 33:
    trend_label = "📉 熊市低位"
    trend_detail = "允许全档位"
else:
    trend_label = "➡️ 中性"
    trend_detail = ""

# ===== 8. 构建消息 =====
vxn_str = f"VXN={vxn:.1f}({vxn_date})" if vxn else "VXN=N/A"
today = datetime.now().strftime("%Y-%m-%d")

# 档位说明
if tier == 0:
    tier_reason = "VXN<24或未触发加仓条件"
else:
    cond_parts = []
    if VXN_THRESHOLDS[tier] > 0:
        cond_parts.append(f"VXN≥{VXN_THRESHOLDS[tier]}")
    cond_parts.append(f"回撤≥{TIERS[tier][3]}%")
    tier_reason = " + ".join(cond_parts)

# 金额明细行
detail_lines = []
detail_lines.append(f"基础定投: ¥{BASE}")
if dd < 3 or (3 <= dd < 5):
    calm_note = f"DD={dd}%→平静区存钱" if dd < 3 else f"DD={dd}%→半额定投"
    detail_lines.append(f"   ├ {calm_note}: ¥{BASE}→¥{base}")
if dd >= 28:
    crash_note = f"DD≥35%→×3" if dd >= 35 else f"DD≥28%→×1.5"
    detail_lines.append(f"   ├ 暴跌扩倍{crash_note}: ¥→¥{base}")
if trend_cut_applied:
    detail_lines.append(f"   ├ 趋势裁剪(52周位{pos:.0f}%>75%): ¥→¥{base}")
if suppress_extra:
    detail_lines.append(f"   └ 高位禁T1/T2加仓: 不加额外")
elif tier > 0:
    detail_lines.append(f"   └ T{tier}×{mult}: +¥{extra}")
detail_lines.append(f"总计: ¥{total}")

body_lines = [
    f"━━━ QQQ 定投建议 · {today} ━━━",
    "",
    f"QQQ: ${price:.2f}  ({chg_pct:+.2f}%)",
    f"{vxn_str} | 回撤={dd}% | 52周位={pos:.0f}% {trend_label}",
    "",
    f"档位: T{tier} {tier_name}",
    f"条件: {tier_reason}" if tier > 0 else f"说明: {tier_reason}",
    "",
    "── 金额明细 ──",
]
body_lines.extend(detail_lines)
body_lines.append("")
# 操作建议文字
if tier == 0:
    action_text = "💰 正常定投"
elif suppress_extra:
    action_text = "☀️ 高位定投(禁加仓)"
elif tier == 1:
    action_text = "💧 小额加仓"
elif tier == 2:
    action_text = "🌊 双倍定投"
elif tier == 3:
    action_text = "⚡ 双倍定投+"
elif tier == 4:
    action_text = "🔥 三倍定投"
else:
    action_text = "🚀 全力加仓"
body_lines.append(f"操作建议: {action_text}")
body_lines.append(f"建议投入: ¥{total}")
body_lines.append("")
body_lines.append("━━━━━━━━━━━━━━━━━━━")
body_lines.append("https://adam-max144.github.io/qqq-monitor/")

body = "\n".join(body_lines)
print(body)

# ===== 9. 发送邮件 =====
try:
    smtp_user = "941189835@qq.com"
    smtp_pass = "ualqcpqiekupbdej"
    smtp_host = "smtp.qq.com"
    smtp_port = 465

    subject = f"📅 QQQ定投建议 | {today} | T{tier} ¥{total}"
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
