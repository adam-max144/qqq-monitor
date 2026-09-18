"""rock_ics.py 的测试套件(把 icalendar 的坑固化成断言, 免得下次重踩)。

Hermetic: 全部离线。四个易踩点各有对应用例 —— UID 稳定性 / 时区语义 / RFC5545 折行 / 字符转义。
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from icalendar import Calendar

import rock_gd as rg
import rock_ics as ri

TZ = rg.TZ_CN
NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)

SYNTH = [
    {"id": 111, "cityName": "广州", "title": '半角,逗号;分号\\反斜杠 换行\n测试',
     "showTime": "2026/10/01 20:00", "siteName": "MAO Livehouse广州（太古仓店）",
     "performers": "A/B", "price": "¥99起"},
    {"id": 222, "cityName": "深圳", "title": "普通标题",
     "showTime": "2026/10/02", "siteName": "HOU LIVE 下沙店", "performers": "C", "price": "¥1起"},
]


def cal_and_events(events=SYNTH, now=NOW):
    cal = ri.build_calendar(events, "测试日历", now)
    return Calendar.from_ical(cal.to_ical()), [v for v in Calendar.from_ical(cal.to_ical()).walk("VEVENT")]


def test_roundtrip_event_count():
    _, vevents = cal_and_events()
    assert len(vevents) == len(SYNTH)


def test_dtstart_is_shanghai_aware_and_not_shifted():
    _, vevents = cal_and_events()
    for v in vevents:
        dt = v["DTSTART"].dt
        assert dt.tzinfo is not None and str(dt.tzinfo) == "Asia/Shanghai"
    assert any(v["DTSTART"].dt.hour == 20 and v["DTSTART"].dt.minute == 0 for v in vevents)
    assert any(v["DTSTART"].dt.hour == 20 for v in vevents)          # 缺时间默认 20:00


def test_dtend_after_dtstart_and_alarm_and_vtimezone():
    cal, vevents = cal_and_events()
    assert all(v["DTEND"].dt > v["DTSTART"].dt for v in vevents)
    assert any(True for v in vevents for _ in v.walk("VALARM"))      # 提前一天提醒
    assert list(cal.walk("VTIMEZONE"))                               # 内嵌时区定义


def test_uid_stable_across_runs():
    """UID 不稳 = 手机日历每次同步都多一份重复场次。"""
    _, a = cal_and_events(now=NOW)
    _, b = cal_and_events(now=NOW + timedelta(days=1))
    assert {v["UID"] for v in a} == {v["UID"] for v in b}
    assert all("111" in str(v["UID"]) or "222" in str(v["UID"]) for v in a)


def test_summary_has_city_prefix_and_escapes_roundtrip():
    _, vevents = cal_and_events()
    titles = [str(v["SUMMARY"]) for v in vevents]
    assert all("｜" in t for t in titles)
    assert any("半角,逗号;分号" in t and "\\反斜杠" in t for t in titles)


def test_lines_fold_within_75_bytes():
    raw = ri.build_calendar(SYNTH, "测试日历", NOW).to_ical().decode("utf-8")
    over = [ln for ln in raw.split("\r\n") if len(ln.encode("utf-8")) > 75]
    assert not over, f"{len(over)} 行超长(中文长标题最容易踩)"


def test_location_and_url_are_set():
    _, vevents = cal_and_events()
    assert all(str(v["LOCATION"]) for v in vevents)
    assert all(str(v["URL"]).startswith(f"{rg.BASE}/event/") for v in vevents)


def test_empty_event_list_is_valid_calendar():
    cal = Calendar.from_ical(ri.build_calendar([], "空", NOW).to_ical())
    assert cal["VERSION"] == "2.0" and not [v for v in cal.walk("VEVENT")]


def test_event_without_date_is_skipped():
    bad = [{"id": 1, "cityName": "广州", "title": "待定", "showTime": "待定"}]
    _, vevents = cal_and_events(bad)
    assert vevents == []


@pytest.mark.parametrize("days", [1, 45, 90])
def test_cli_writes_file_with_frozen_data(monkeypatch, tmp_path, days):
    """CLI 走同一套 collect + build_calendar(网络被 stub 掉)。"""
    evs = [{"id": 9, "title": "T", "showTime": "2026/10/01 20:00", "cityName": "广州",
            "siteName": "V", "performers": "P", "price": "¥1"}]
    monkeypatch.setattr(rg, "collect", lambda cities, h: (evs, len(evs), 1))
    out = tmp_path / "x.ics"
    monkeypatch.setattr("sys.argv", ["rock_ics.py", "--days", str(days), "--out", str(out)])
    assert ri.main() == 0
    assert len([v for v in Calendar.from_ical(out.read_bytes()).walk("VEVENT")]) == 1


def test_cli_refuses_to_overwrite_on_zero_response(monkeypatch, tmp_path):
    monkeypatch.setattr(rg, "collect", lambda cities, h: ([], 0, 0))
    out = tmp_path / "keep.ics"
    out.write_text("OLD", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["rock_ics.py", "--out", str(out)])
    assert ri.main() == 2
    assert out.read_text(encoding="utf-8") == "OLD"      # 抓不到就保留旧日历, 别清空
