"""cn_calendar.py — A股(沪深)交易日历, 供定时任务判「今天是否开市」。

为什么要有它: premium-alert / q70-daily 都是**自然日** cron, A股休市日照跑 ——
休市日行情是陈旧数据, 算出来的溢价/净值无意义(2026 年有 19 个工作日休市)。
此前只有「周末判断」, 法定节假日(春节/国庆)完全没覆盖。

依赖: `holidays`(建议 `pip install holidays`)。没装时**降级为「只看周末」**并按 fail-open 处理
(宁可多跑一次, 也不要因为缺依赖而静默漏掉开市日), 同时打印提示。

用法:
    from cn_calendar import is_trading_day, today_cn
    if not is_trading_day("cn", today_cn()):   # 休市 → 直接跳过
        return 0

命令行:
    python scripts/cn_calendar.py                 # 今天是否开市 + 之后 5 个交易日
    python scripts/cn_calendar.py --closed 2026   # 全年工作日休市清单
    python scripts/cn_calendar.py --days 2026-09-28:2026-10-12
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

if hasattr(sys.stdout, "reconfigure"):          # Windows 控制台默认 GBK
    sys.stdout.reconfigure(encoding="utf-8")

try:
    import holidays
    HAVE_HOLIDAYS = True
except ImportError:                             # pragma: no cover - 环境差异
    holidays = None
    HAVE_HOLIDAYS = False

MARKETS = {"cn": ("CN", "A股(沪深)"), "hk": ("HK", "港股"), "us": ("US", "美股(联邦假日近似)")}
_CACHE: dict[tuple[str, int], dict[dt.date, str]] = {}
_WARNED = False


def today_cn() -> dt.date:
    """北京「今天」。⚠️ 用固定 +08:00 偏移, 不依赖本机时区(CI runner 是 UTC)。"""
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()


def _holiday_map(market: str, year: int) -> dict[dt.date, str]:
    key = (market, year)
    if key not in _CACHE:
        code, _ = MARKETS[market]
        _CACHE[key] = dict(holidays.country_holidays(code, years=year)) if HAVE_HOLIDAYS else {}
    return _CACHE[key]


def holiday_name(market: str, d: dt.date) -> str | None:
    return _holiday_map(market, d.year).get(d)


def is_trading_day(market: str, d: dt.date) -> bool:
    """A股/港股: 周一~周五 且 非法定节假日。

    ⚠️ 只看 weekday() —— **调休补班的周六日交易所不开市**(holidays 会把它们标成 workday,
    但交易日不能拿那个反推)。缺 holidays 时退化为「只看周末」(fail-open)。
    """
    global _WARNED
    if d.weekday() >= 5:
        return False
    if not HAVE_HOLIDAYS:
        if not _WARNED:
            print("⚠️ 未安装 holidays → 只能按周末判断(法定节假日无法排除); pip install holidays 可根治")
            _WARNED = True
        return True
    return holiday_name(market, d) is None


def trading_days(market: str, start: dt.date, end: dt.date) -> list[dt.date]:
    out, d = [], start
    while d <= end:
        if is_trading_day(market, d):
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def closed_days(market: str, year: int) -> list[tuple[dt.date, str]]:
    """该年「工作日休市」= 法定节假日(周末单列无意义)。"""
    return [(d, name) for d, name in sorted(_holiday_map(market, year).items()) if d.year == year and d.weekday() < 5]


def next_trading_days(market: str, n: int, frm: dt.date | None = None) -> list[dt.date]:
    d = frm or today_cn()
    out = []
    while len(out) < n:
        if is_trading_day(market, d):
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="A股/港股/美股 交易日历")
    ap.add_argument("--market", default="cn", choices=list(MARKETS))
    ap.add_argument("--closed", type=int, help="某年工作日休市清单")
    ap.add_argument("--days", help="区间 A:B 逐日列出")
    a = ap.parse_args()
    if a.closed:
        rows = closed_days(a.market, a.closed)
        print(f"{MARKETS[a.market][1]} {a.closed} 年工作日休市 {len(rows)} 天:")
        for d, name in rows:
            print(f"  {d} {d.strftime('%a')}  {name}")
        return 0
    if a.days:
        s, _, e = a.days.partition(":")
        sd, ed = dt.date.fromisoformat(s), dt.date.fromisoformat(e or s)
        d = sd
        while d <= ed:
            st = "⚪周末" if d.weekday() >= 5 else (f"⛔{holiday_name(a.market, d)}" if holiday_name(a.market, d) else "✅开市")
            print(f"  {d} {d.strftime('%a')} {st}")
            d += dt.timedelta(days=1)
        return 0
    t = today_cn()
    name = holiday_name(a.market, t)
    print(f"{MARKETS[a.market][1]} 今天 {t} {t.strftime('%a')}: "
          f"{'⛔休市(' + name + ')' if name else ('✅开市' if is_trading_day(a.market, t) else '⛔休市(周末)')}")
    print("之后 5 个交易日:", ", ".join(str(d) for d in next_trading_days(a.market, 5)))
    print(f"holidays 后端: {'已装' if HAVE_HOLIDAYS else '未装(仅周末判断)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
