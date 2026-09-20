#!/usr/bin/env python3
"""广东摇滚演出日报 — 抓秀动(showstart.com) 服务端渲染页 → 汇总 → 邮件推送。

用法:
  python scripts/rock_gd.py --dry          # 只打印, 不发邮件(默认)
  python scripts/rock_gd.py --send         # 抓取 + 发邮件
  python scripts/rock_gd.py --days 30 --cities 广州,深圳
  python scripts/rock_gd.py --html out.html

数据源: https://www.showstart.com/event/list?cityCode=<code>&showStyle=2 (摇滚)
        页面是 Nuxt SSR, 事件列表内嵌在 window.__NUXT__ 的 listData 里 —— 不需要秀动
        那个要 MD5 签名 + WAF token 的私有 API(http://api3.showstart.com 一律返回
        sys001「参数不全」, 已实测放弃)。SSR 页面普通 UA 即可拿到完整列表。
凭据(仅发邮件时需要): SMTP_USER / SMTP_PASS / MAIL_TO (QQ邮箱 smtp.qq.com:465)
环境变量: DRY_RUN=1 等价 --dry; HORIZON_DAYS / CITIES 可覆盖默认值。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import sys
import urllib.request

from net import fetch as net_fetch      # 带退避重试的取数(scripts/net.py; tenacity 可选)
from datetime import datetime, timedelta, timezone
from email.header import Header
from email.mime.text import MIMEText

# 广东主要城市 → 秀动 cityCode(取自 showstart 城市配置, 2026-09 实测)
CITIES: list[tuple[str, str]] = [
    ("广州", "20"),
    ("深圳", "755"),
    ("佛山", "757"),
    ("东莞", "769"),
    ("珠海", "756"),
    ("中山", "760"),
    ("惠州", "752"),
    ("汕头", "754"),
]
STYLE_ROCK = "2"   # 秀动风格筛选: 2 = 摇滚
BASE = "https://www.showstart.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
PAGE_SIZE = 20     # SSR 每页 20 条
MAX_PAGES = 3      # 每城最多翻 3 页
HORIZON_DAYS = 45  # 只报未来 N 天
PERFORMERS_MAX = 60
PAGE_URL_TMPL = BASE + "/event/list?cityCode={code}&showStyle=" + STYLE_ROCK + "&pageNo={page}"

try:  # 北京时区: CI(UTC) 上必须显式转换, 否则「今天/明天」与日期过滤都会错一天
    from zoneinfo import ZoneInfo
    TZ_CN: timezone | ZoneInfo = ZoneInfo("Asia/Shanghai")
except Exception:  # noqa: BLE001
    TZ_CN = timezone(timedelta(hours=8))


def now_cn() -> datetime:
    return datetime.now(TZ_CN).replace(tzinfo=None)


def run_url() -> str:
    """可点的运行日志地址 — CI 里指向本次 run, 本地跑退回 Actions 首页。"""
    run = os.environ.get("GITHUB_RUN_ID")
    base = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "adam-max144/qqq-monitor")
    return f"{base}/{repo}/actions/runs/{run}" if run else f"{base}/{repo}/actions"


def _parse_iso(s: object) -> datetime | None:
    """ISO 时间串 → datetime; 解析不了返回 None(不抛异常, 调用方跳过该条)。"""
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def already_sent_today(workflow: str = "rock-gd.yml") -> str | None:
    """今天是否已有成功的 run(北京时间口径) —— 备用 cron 靠它避免重复发信。

    只在 CI 里生效(GITHUB_TOKEN + GITHUB_REPOSITORY 都在时); 本地跑返回 None。
    查询失败时**按未发送处理**(fail-open): 宁可多收一封, 也不要整天收不到。
    """
    tok, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (tok and repo):
        return None
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    url = f"{api}/repos/{repo}/actions/workflows/{workflow}/runs?per_page=20"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
        "User-Agent": "rock-gd-digest"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            runs = json.load(r)["workflow_runs"]
    except Exception as e:  # noqa: BLE001
        print(f"  (幂等检查失败, 按未发送处理: {type(e).__name__})", file=sys.stderr)
        return None
    me, today = os.environ.get("GITHUB_RUN_ID"), now_cn().date()
    for r in runs:
        if str(r.get("id")) == me or r.get("conclusion") != "success":
            continue
        d = _parse_iso(r.get("created_at"))
        if d and d.astimezone(TZ_CN).date() == today:
            return f"run {r['id']}"
    return None


# ---------------------------------------------------------------- fetch / parse
def curl(url: str, timeout: int = 30) -> str:
    """取秀动页面(带退避重试 —— 见 scripts/net.py; 失败返回空串由调用方跳过)。"""
    try:
        return net_fetch(url, ref="https://www.showstart.com/", timeout=timeout,
                         headers={"User-Agent": UA})
    except Exception as e:  # noqa: BLE001
        print(f"  ! fetch fail {url}: {type(e).__name__}: {e}", file=sys.stderr)
        return ""


def _split_js_args(tail: str) -> list[str]:
    """Split a JS argument list on top-level commas (handles strings/nesting)."""
    args, cur, depth, instr, esc = [], "", 0, False, False
    bs = chr(92)
    for ch in tail:
        if instr:
            cur += ch
            if esc:
                esc = False
            elif ch == bs:
                esc = True
            elif ch == '"':
                instr = False
            continue
        if ch == '"':
            instr = True
            cur += ch
        elif ch in "([{":
            depth += 1
            cur += ch
        elif ch in ")]}":
            if depth == 0 and ch == ")":
                break
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            args.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        args.append(cur.strip())
    return args


def _var_map(page: str) -> dict[str, str]:
    """Nuxt 把字面量压缩成 IIFE 形参: __NUXT__=(function(a,b,..){..}}(1,"流行",..))"""
    m = re.search(r"__NUXT__=\(function\(([^)]*)\)\{", page)
    if not m:
        return {}
    names = m.group(1).split(",")
    k = page.rfind("}}(", 0, page.find("</script>", page.find("__NUXT__=")))
    return dict(zip(names, _split_js_args(page[k + 3:])))


def parse_events(page: str) -> list[dict]:
    """Extract window.__NUXT__.data[0].listData from the SSR page."""
    i = page.find("listData:[")
    if i < 0:
        return []
    seg, depth, raw = page[i + len("listData:"):], 0, None
    for k, ch in enumerate(seg):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                raw = seg[:k + 1]
                break
    if raw is None:
        return []
    vm = _var_map(page)
    fixed = re.sub(r"([:,])([A-Za-z_$][A-Za-z0-9_$]*)(?=[,}])",
                   lambda m: m.group(1) + vm.get(m.group(2), m.group(2)), raw)
    fixed = re.sub(r"([{,])([A-Za-z_][A-Za-z0-9_]*):", r'\1"\2":', fixed)
    try:
        data = json.loads(fixed)
    except Exception as e:  # noqa: BLE001  页面改版时宁可少报也不要炸
        print(f"  ! parse fail: {e}", file=sys.stderr)
        return []
    return [e for e in data if isinstance(e, dict) and e.get("id")]


_DATE_RE = re.compile(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


def event_dt(ev: dict) -> datetime | None:
    s = str(ev.get("showTime", ""))
    m = _DATE_RE.search(s)
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    hm = _TIME_RE.search(s)
    hh, mi = (int(hm.group(1)), int(hm.group(2))) if hm else (20, 0)
    try:
        # naive 北京时间: 全脚本统一在「北京本地时刻」空间里比较, 见 now_cn()
        return datetime(y, mo, d, hh, mi)  # noqa: DTZ001
    except ValueError:
        return None


def collect(cities: list[tuple[str, str]], horizon: int) -> tuple[list[dict], int, int]:
    """Return (upcoming events sorted by datetime, raw rows seen, cities that responded)."""
    today = now_cn().replace(hour=0, minute=0, second=0, microsecond=0)
    limit = today + timedelta(days=horizon)
    out: dict[int, dict] = {}
    total = 0
    ok_cities = 0
    for name, code in cities:
        got_city = False
        for page in range(1, MAX_PAGES + 1):
            evs = parse_events(curl(PAGE_URL_TMPL.format(code=code, page=page)))
            if not evs:
                break
            got_city = True
            total += len(evs)
            for ev in evs:
                ev["cityName"] = name
                dt = event_dt(ev)
                if dt is None or dt < today or dt > limit:
                    continue
                out.setdefault(ev["id"], ev)
            if len(evs) < PAGE_SIZE:
                break
        ok_cities += 1 if got_city else 0
        print(f"  {name}: 累计 {len(out)} 场(未来{horizon}天)")
    # 保留的事件都带合法日期, 「无日期」排序兜底不改变顺序
    return sorted(out.values(), key=lambda e: (event_dt(e) is None, event_dt(e) or today)), total, ok_cities


# ---------------------------------------------------------------- render
def fmt_day(dt: datetime, today: datetime) -> str:
    delta = (dt.date() - today.date()).days
    wd = "一二三四五六日"[dt.weekday()]
    tag = {0: "今天", 1: "明天", 2: "后天"}.get(delta, "")
    return f"{dt.month}/{dt.day} 周{wd}{'(' + tag + ')' if tag else ''} {dt:%H:%M}"


def short_performers(s: str) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= PERFORMERS_MAX else s[:PERFORMERS_MAX - 1] + "…"


def group(events: list[dict], cities: list[tuple[str, str]]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    for ev in events:
        by.setdefault(ev["cityName"], []).append(ev)
    return {c: by[c] for c, _ in cities if c in by}


def build_html(events: list[dict], cities: list[tuple[str, str]], horizon: int) -> str:
    today = now_cn()
    by = group(events, cities)
    rows = []
    for city, evs in by.items():
        rows.append(f'<tr><td colspan="3" style="padding:16px 0 6px;font-size:15px;font-weight:700;'
                    f'color:#d1345b;border-bottom:2px solid #f0f0f0">{city} · {len(evs)} 场</td></tr>')
        for ev in evs:
            dt = event_dt(ev)
            link = f"{BASE}/event/{ev['id']}"
            site = ev.get("siteName") or ""
            rows.append(
                '<tr>'
                f'<td style="padding:9px 10px 9px 0;white-space:nowrap;vertical-align:top;'
                f'color:#0a8f4d;font-weight:700;font-size:13px">{fmt_day(dt, today)}</td>'
                f'<td style="padding:9px 8px 9px 0;vertical-align:top">'
                f'<a href="{link}" style="color:#1a56db;text-decoration:none;font-weight:600">'
                f'{ev.get("title", "?")}</a>'
                f'<div style="color:#666;font-size:12px;margin-top:3px">'
                f'{short_performers(ev.get("performers", ""))}'
                f'{" ｜ " + site if site else ""}</div></td>'
                f'<td style="padding:9px 0;white-space:nowrap;vertical-align:top;color:#c2410c;'
                f'font-weight:600;font-size:13px">{ev.get("price", "")}</td></tr>')
    if not rows:
        rows.append(f'<tr><td colspan="3" style="padding:24px;color:#666;text-align:center">'
                    f'未来 {horizon} 天内没有抓到摇滚演出</td></tr>')
    return (
        '<html><body style="font-family:-apple-system,\'PingFang SC\',\'Microsoft YaHei\','
        'sans-serif;max-width:660px;margin:0 auto;padding:14px;color:#222">'
        f'<h2 style="margin:0 0 4px;font-size:19px">🎸 广东摇滚演出 · 未来 {horizon} 天</h2>'
        f'<div style="color:#666;font-size:12px;margin-bottom:8px">'
        f'秀动「摇滚」风格 · 共 {len(events)} 场 / {len(by)} 城 · 数据抓取于 {today:%Y-%m-%d %H:%M}(北京)</div>'
        f'<table style="width:100%;border-collapse:collapse;font-size:14px">{"".join(rows)}</table>'
        '<div style="color:#999;font-size:11px;margin-top:18px;line-height:1.7">'
        '点标题进秀动详情页购票 · 仅含秀动标注「摇滚」的演出, 金属/朋克/独立等其它标签不在内 '
        '(需要可加) · 本邮件由 GitHub Actions 每日 10:00(北京) 自动生成, 无需人工维护</div>'
        '</body></html>')


def build_text(events: list[dict], cities: list[tuple[str, str]], horizon: int) -> str:
    today = now_cn()
    by = group(events, cities)
    lines = [f"广东摇滚演出 · 未来 {horizon} 天 (秀动/摇滚) — {today:%Y-%m-%d %H:%M} 北京",
             f"共 {len(events)} 场 / {len(by)} 城", ""]
    for city, evs in by.items():
        lines.append(f"【{city}】{len(evs)} 场")
        for ev in evs:
            dt = event_dt(ev)
            lines.append(f"  {dt:%m-%d %H:%M}  {ev.get('title', '?')}")
            lines.append(f"           {short_performers(ev.get('performers', ''))}"
                         f"  |  {ev.get('siteName', '')}  |  {ev.get('price', '')}")
            lines.append(f"           {BASE}/event/{ev['id']}")
        lines.append("")
    if not events:
        lines.append(f"未来 {horizon} 天内没有抓到摇滚演出。")
    return "\n".join(lines)


# ---------------------------------------------------------------- mail
def _mask(addr: str) -> str:
    """941189835@qq.com → 941***@qq.com —— 日志里可核对收件人数, 又不泄露完整地址。"""
    return addr[:3] + "***" + addr[addr.index("@"):] if "@" in addr else "***"


def send_mail(subject: str, html_body: str, text_body: str) -> str:
    user = os.environ.get("SMTP_USER", "").strip()
    pwd = os.environ.get("SMTP_PASS", "").strip()
    to = [x.strip() for x in (os.environ.get("MAIL_TO") or user).split(",") if x.strip()]
    if not (user and pwd):
        return "mail: skip (缺少 SMTP_USER / SMTP_PASS)"
    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = user
    msg["To"] = ", ".join(to)
    s = smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=30)
    try:
        s.login(user, pwd)
        s.sendmail(user, to, msg.as_string())
    finally:
        s.close()
    return f"mail: ok -> {len(to)} 个收件人: " + ", ".join(_mask(x) for x in to)


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="发邮件(默认只打印)")
    ap.add_argument("--dry", action="store_true", help="只看结果, 不发邮件")
    ap.add_argument("--days", type=int, default=int(os.environ.get("HORIZON_DAYS") or HORIZON_DAYS))
    ap.add_argument("--cities", default=os.environ.get("CITIES", ""), help="逗号分隔, 默认全部")
    ap.add_argument("--html", default="", help="把 HTML 正文另存到该路径")
    a = ap.parse_args()
    if os.environ.get("DRY_RUN") == "1":
        a.send = False

    cities = CITIES
    if a.cities:
        want = {c.strip() for c in a.cities.split(",") if c.strip()}
        cities = [c for c in CITIES if c[0] in want] or CITIES

    events, total, ok_cities = collect(cities, a.days)
    print(f"抓取 {total} 条原始记录 / {ok_cities}/{len(cities)} 城有响应 "
          f"→ 未来 {a.days} 天内 {len(events)} 场")

    if total == 0:
        # 云端自动化最怕「静默死亡」: 站点改版/被拦时, 至少让用户收到一封告警而不是什么都没有
        warn = (f"秀动页面 {len(cities)} 个城市全部返回 0 条记录 —— 站点可能改版/被拦。\n"
                f"本次未发送正常日报, 请查看运行日志: {run_url()}")
        print("!! " + warn, file=sys.stderr)
        try:
            print(send_mail("⚠️ 广东摇滚日报抓取失败(0 条)", f"<pre>{warn}</pre>", warn))
        except Exception as e:  # noqa: BLE001
            print(f"!! 告警邮件也发不出去: {e}", file=sys.stderr)
        return 2

    html_body = build_html(events, cities, a.days)
    text_body = build_text(events, cities, a.days)
    if a.html:
        with open(a.html, "w", encoding="utf-8") as f:
            f.write(html_body)

    if a.send:
        # 幂等只对「定时任务」生效: 手动触发(Actions 点 Run workflow)和本地跑一律照发
        if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
            dup = already_sent_today()
            if dup:
                print(f"今日已成功发送过({dup}) → 本次跳过(备用 cron 去重, 不重复发信)")
                return 0
        subject = f"🎸 广东摇滚 {len(events)} 场 · 未来{a.days}天 · {now_cn():%m-%d}"
        print(send_mail(subject, html_body, text_body))
    else:
        print(text_body[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
