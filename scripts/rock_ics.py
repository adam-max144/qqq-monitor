#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「广东摇滚演出」导出成 .ics 日历 —— 手机订阅一次, 之后自动更新, 零维护。

用法:
  python scripts/rock_ics.py                        # 未来45天 → rock.ics
  python scripts/rock_ics.py --days 30 --out x.ics --cities 广州,深圳

设计要点(踩过的):
  · UID 必须稳定(用 showstart 事件 id) —— 否则每跑一次, 手机日历里就会多出一份重复场次
  · DTSTART 用 Asia/Shanghai 且**内嵌 VTIMEZONE** —— 只写 TZID 不给定义, 部分客户端会当本地时间
  · 每行必须 ≤75 字节(RFC5545 折行) —— 中文标题很长, 不折行会被严格的解析器拒绝
  · SUMMARY 里塞城市前缀, 因为订阅型日历只按标题搜
复用 rock_gd.py 的抓取/过滤逻辑, 只做「事件 → VEVENT」的转换。
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rock_gd as rg  # noqa: E402

from icalendar import Calendar, Event, Timezone as IcalTimezone  # noqa: E402

PRODID = "-//qqq-monitor//GD rock digest//CN"
UID_DOMAIN = "showstart.gd.qqq-monitor"
TZID = "Asia/Shanghai"


def build_calendar(events: list[dict], calname: str, now: datetime | None = None) -> Calendar:
    cal = Calendar()
    cal.add("prodid", PRODID)
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", calname)
    cal.add("x-wr-timezone", TZID)

    # 内嵌 VTIMEZONE: 让客户端知道 Asia/Shanghai 到底是什么(否则可能按本地时区解释)
    try:
        cal.add_component(IcalTimezone.from_tzinfo(rg.TZ_CN, tzid=TZID))
    except Exception as e:  # noqa: BLE001  老版本/拿不到 tzinfo 时降级为纯 TZID
        print(f"  (VTIMEZONE 生成失败, 降级为纯 TZID: {e})", file=sys.stderr)

    stamp = now or datetime.now(timezone.utc)
    for ev in events:
        end = rg.event_dt(ev)
        if end is None:
            continue
        e = Event()
        e.add("uid", f"{UID_DOMAIN}-{ev['id']}")
        e.add("dtstamp", stamp)
        e.add("dtstart", end.replace(tzinfo=rg.TZ_CN))          # 演出通常 2-3 小时
        e.add("dtend", (end + timedelta(hours=3)).replace(tzinfo=rg.TZ_CN))
        e.add("summary", f"{ev['cityName']}｜{ev.get('title', '')}")
        loc = " ".join(x for x in (ev.get("siteName"), ev.get("cityName")) if x)
        if loc:
            e.add("location", loc)
        e.add("url", f"{rg.BASE}/event/{ev['id']}")
        desc = [f"艺人: {ev.get('performers', '')}", f"票价: {ev.get('price', '')}",
                f"购票: {rg.BASE}/event/{ev['id']}", "来源: 秀动 showstart.com"]
        e.add("description", "\n".join(desc))
        e.add_component(_alarm())
        cal.add_component(e)
    return cal


def _alarm():
    from icalendar import Alarm
    al = Alarm()
    al.add("action", "DISPLAY")
    al.add("description", "演出明天, 记得看票")
    al.add("trigger", timedelta(days=-1))
    return al


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--out", default="rock.ics")
    ap.add_argument("--cities", default="")
    a = ap.parse_args()

    cities = rg.CITIES
    if a.cities:
        want = {c.strip() for c in a.cities.split(",") if c.strip()}
        cities = [c for c in rg.CITIES if c[0] in want] or rg.CITIES

    events, total, ok = rg.collect(cities, a.days)
    print(f"抓取 {total} 条 → 未来 {a.days} 天 {len(events)} 场 ({ok}/{len(cities)} 城有响应)")
    if total == 0:
        print("零响应 → 不覆盖已有 .ics", file=sys.stderr)
        return 2

    cal = build_calendar(events, f"广东摇滚演出(未来{a.days}天) · 秀动")
    data = cal.to_ical()
    Path(a.out).write_bytes(data)
    print(f"写出 {a.out}: {len(data)} bytes / {len(events)} 个 VEVENT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
