"""rock_gd.py 的可复跑测试套件(替代此前散落的 ad-hoc 校验脚本)。

Hermetic: 除标 @pytest.mark.network 的用例外全部离线。
"""
import io
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest
import rock_gd as rg
from freezegun import freeze_time


# --- fixtures ---------------------------------------------------------------
# 形状与真实页面一致: Nuxt 把字面量压成 IIFE 形参, listData 里是裸标识符
def page_with(events_js: str) -> str:
    return ('<!doctype html><html><script>window.__NUXT__=(function(a,b,c,d,e,f){return '
            '{layout:"default",data:[{totalCount:9,listData:[' + events_js + ']}]}'
            '}(1,"流行",2,"广州","MAO Livehouse广州（太古仓店）","SDlivehouse"))'
            '</script></html>')


def ev(id_, title, when, site="e"):
    return (f'{{"id":{id_},"title":"{title}","showTime":"{when}","siteName":{site},'
            f'"cityName":d,"performers":"band","price":"¥10起"}}')


PAGE = page_with(ev(1, "硬摇滚之夜", "2026/10/01 20:00") + "," +
                 ev(2, "盯鞋专场", "2026/11/01", "f"))


def fake_collect(dates=("2026-10-01", "2026-10-05")):
    out = [{"id": i + 1, "title": f"演出{i+1}", "cityName": "广州",
            "showTime": f"{d.replace('-', '/')} 20:00", "siteName": "MAO Livehouse广州（太古仓店）",
            "performers": "band", "price": "¥10起"} for i, d in enumerate(dates)]
    return out, len(dates), 1


# --- 解析层 -----------------------------------------------------------------
def test_parse_events_resolves_minified_vars():
    evs = rg.parse_events(PAGE)
    assert len(evs) == 2
    assert evs[0]["siteName"] == "MAO Livehouse广州（太古仓店）"   # 裸标识符 e 已解引用
    assert evs[0]["cityName"] == "广州"                            # 裸标识符 c 已解引用
    assert evs[1]["siteName"] == "SDlivehouse"


def test_parse_events_bad_pages_return_empty():
    for bad in ("<html>no nuxt</html>", "", '<html>data:[{"id":1,"c":zz}]</html>'):
        assert rg.parse_events(bad) == []


@pytest.mark.parametrize("raw,expect", [
    ("2026/10/24 20:00", (2026, 10, 24, 20, 0)),
    ("2026-10-24 19:30", (2026, 10, 24, 19, 30)),
    ("2026/10/24", (2026, 10, 24, 20, 0)),      # 无时间 → 默认 20:00
])
def test_event_dt(raw, expect):
    d = rg.event_dt({"showTime": raw})
    assert (d.year, d.month, d.day, d.hour, d.minute) == expect


def test_event_dt_garbage_is_none():
    assert rg.event_dt({"showTime": "待定"}) is None
    assert rg.event_dt({}) is None


def test_split_js_args_handles_cjk_comma_quotes():
    got = rg._split_js_args('1,2,"广州",3,"MAO Livehouse广州（太古仓店）","SDlivehouse")')
    assert got[-1] == '"SDlivehouse"' and got[2] == '"广州"'


def test_validate_script_syntax():
    src = Path(rg.__file__).read_text(encoding="utf-8")
    compile(src, rg.__file__, "exec")            # 语法自检(等价 py_compile, 但快)


# --- 时间窗口 / 时区(CI 是 UTC, 必须按北京算) --------------------------------
@freeze_time("2026-09-18 10:00:00")
def test_horizon_filter_uses_beijing_tz(monkeypatch):
    page = page_with(",".join([
        ev(1, "过去", "2026/09/01 20:00"),      # 已过期 → 丢
        ev(2, "今天", "2026/09/18 20:00"),
        ev(3, "窗口内", "2026/10/01 20:00"),
        ev(4, "太远", "2026/12/25 20:00"),      # 超出 45 天 → 丢
    ]))
    monkeypatch.setattr(rg, "curl", lambda url, timeout=30: page)
    evs, total, ok = rg.collect([("广州", "20")], horizon=45)
    assert [e["id"] for e in evs] == [2, 3]
    assert total == 4 and ok == 1


def test_now_cn_is_utc_plus_8():
    from datetime import datetime, timezone
    delta = rg.now_cn() - datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs(delta.total_seconds() - 8 * 3600) < 5


def test_collect_sorts_by_datetime(monkeypatch):
    page = page_with(",".join([ev(2, "晚", "2026/10/09 20:00"), ev(1, "早", "2026/10/01 20:00")]))
    monkeypatch.setattr(rg, "curl", lambda url, timeout=30: page)
    with freeze_time("2026-09-18"):
        evs, _, _ = rg.collect([("广州", "20")], horizon=45)
    assert [e["id"] for e in evs] == [1, 2]


# --- 渲染 -------------------------------------------------------------------
def test_build_html_groups_city_once_and_links_each_event():
    evs = fake_collect()[0] + [dict(fake_collect()[0][0], id=99, cityName="深圳")]
    html = rg.build_html(evs, rg.CITIES, 45)
    assert html.count("广州 · ") == 1 and html.count("深圳 · ") == 1
    assert html.count("https://www.showstart.com/event/") == len(evs)


def test_build_html_empty_still_renders():
    assert "没有抓到摇滚演出" in rg.build_html([], rg.CITIES, 30)


def test_build_text_groups_and_marks_beijing():
    txt = rg.build_text(fake_collect()[0], rg.CITIES, 45)
    assert "【广州】" in txt and txt.count("【广州】") == 1 and "北京" in txt.splitlines()[0]


def test_short_performers_truncates():
    assert len(rg.short_performers("X" * 300)) == rg.PERFORMERS_MAX
    assert rg.short_performers("  a   b ") == "a b"


def test_html_has_no_raw_script_tag():
    assert "<script" not in rg.build_html(fake_collect()[0], rg.CITIES, 45).lower()


# --- run_url ----------------------------------------------------------------
def test_run_url_local_falls_back_to_actions_home(monkeypatch):
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    assert rg.run_url().endswith("/qqq-monitor/actions")


def test_run_url_in_ci_points_to_run(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "999")
    monkeypatch.setenv("GITHUB_REPOSITORY", "adam-max144/qqq-monitor")
    assert rg.run_url().endswith("/actions/runs/999")


# --- main(): 失败告警 / 正常发送 / 缺凭据 ------------------------------------
def run_main(monkeypatch, argv, collect_ret, mail_ret="mail: ok -> stub"):
    calls = []
    monkeypatch.setattr(rg, "collect", lambda c, h: collect_ret)
    monkeypatch.setattr(rg, "send_mail",
                        lambda s, h, t: (calls.append((s, h, t)), mail_ret)[1])
    monkeypatch.setattr(sys, "argv", ["rock_gd.py", *argv])
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = rg.main()
    return code, calls, out.getvalue(), err.getvalue()


def test_zero_records_triggers_alert_and_exit2(monkeypatch):
    code, calls, _, err = run_main(monkeypatch, ["--send"], ([], 0, 0))
    assert code == 2                                   # CI 标红, 不静默
    assert len(calls) == 1 and calls[0][0].startswith("⚠️ 广东摇滚日报抓取失败")
    assert rg.run_url() in calls[0][2] and "未发送正常日报" in calls[0][2]
    assert "0 条记录" in err                            # 日志留痕


def test_alert_mail_failure_keeps_exit2(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(rg, "collect", lambda c, h: ([], 0, 0))
    monkeypatch.setattr(rg, "send_mail", boom)
    monkeypatch.setattr(sys, "argv", ["rock_gd.py", "--send"])
    err = io.StringIO()
    with redirect_stdout(io.StringIO()), redirect_stderr(err):
        code = rg.main()
    assert code == 2 and "告警邮件也发不出去" in err.getvalue()


def test_normal_path_sends_exactly_one_mail(monkeypatch):
    code, calls, _, _ = run_main(monkeypatch, ["--send"], fake_collect())
    assert code == 0 and len(calls) == 1
    assert "🎸 广东摇滚" in calls[0][0] and "未来45天" in calls[0][0]


def test_dry_run_never_sends(monkeypatch):
    code, calls, out, _ = run_main(monkeypatch, ["--send"], fake_collect())
    assert code == 0 and len(calls) == 1
    code, calls, out, _ = run_main(monkeypatch, ["--dry"], fake_collect())
    assert code == 0 and calls == [] and "广州" in out


def test_dry_run_env_var_disables_send(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    code, calls, _, _ = run_main(monkeypatch, ["--send"], fake_collect())
    assert code == 0 and calls == []


def test_missing_credentials_skips_without_raising(monkeypatch):
    for k in ("SMTP_USER", "SMTP_PASS", "MAIL_TO"):
        monkeypatch.delenv(k, raising=False)
    assert rg.send_mail("s", "<b>x</b>", "x").startswith("mail: skip")


def test_mail_to_accepts_multiple_recipients(monkeypatch):
    """MAIL_TO 支持逗号分隔多收件人(qq + foxmail)。"""
    got = {}

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def login(self, u, p):
            got["user"] = u

        def sendmail(self, frm, to, msg):
            got["to"] = to

        def close(self):
            pass

    monkeypatch.setenv("SMTP_USER", "a@qq.com")
    monkeypatch.setenv("SMTP_PASS", "x")
    monkeypatch.setenv("MAIL_TO", "941189835@qq.com, evansunyifei@foxmail.com")
    monkeypatch.setattr(rg.smtplib, "SMTP_SSL", FakeSMTP)
    out = rg.send_mail("s", "<b>x</b>", "x")
    assert got["to"] == ["941189835@qq.com", "evansunyifei@foxmail.com"]
    assert "2 个收件人" in out and "foxmail.com" in out
    assert "evansunyifei" not in out          # 日志脱敏: 不打印完整地址


def test_mask_helper():
    assert rg._mask("evansunyifei@foxmail.com") == "eva***@foxmail.com"
    assert rg._mask("no-at-sign") == "***"


# --- 幂等(备用 cron 去重) ---------------------------------------------------
def test_already_sent_today_local_returns_none(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert rg.already_sent_today() is None


def test_already_sent_today_detects_same_day_success(monkeypatch):
    import json as _json
    today = rg.now_cn().date().isoformat()
    payload = {"workflow_runs": [
        {"id": 999, "conclusion": "success", "created_at": f"{today}T02:05:00Z"},   # 今天(北京)
        {"id": 111, "conclusion": "success", "created_at": "2020-01-01T02:00:00Z"},  # 很久以前
        {"id": 222, "conclusion": "failure", "created_at": f"{today}T02:00:00Z"},   # 失败不算
    ]}

    class R:
        def read(self):
            return _json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "adam-max144/qqq-monitor")
    monkeypatch.setenv("GITHUB_RUN_ID", "555")
    monkeypatch.setattr(rg.urllib.request, "urlopen", lambda req, timeout=20: R())
    assert rg.already_sent_today() == "run 999"


def test_already_sent_today_ignores_own_run(monkeypatch):
    import json as _json
    today = rg.now_cn().date().isoformat()
    payload = {"workflow_runs": [{"id": 555, "conclusion": "success",
                                  "created_at": f"{today}T02:05:00Z"}]}

    class R:
        def read(self):
            return _json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "r/r")
    monkeypatch.setenv("GITHUB_RUN_ID", "555")
    monkeypatch.setattr(rg.urllib.request, "urlopen", lambda req, timeout=20: R())
    assert rg.already_sent_today() is None


def test_already_sent_today_fails_open(monkeypatch):
    def boom(req, timeout=20):
        raise OSError("network down")

    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "r/r")
    monkeypatch.setattr(rg.urllib.request, "urlopen", boom)
    assert rg.already_sent_today() is None      # 宁可多收一封, 也不能整天收不到


def test_main_skips_send_when_already_sent(monkeypatch):
    """定时任务(schedule)当天已发过 → 跳过, 不重复发信。"""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setattr(rg, "already_sent_today", lambda *a, **k: "run 999")
    code, calls, out, _ = run_main(monkeypatch, ["--send"], fake_collect())
    assert code == 0 and calls == [] and "今日已成功发送过" in out


def test_manual_dispatch_always_sends(monkeypatch):
    """手动触发/本地跑不受幂等约束 —— 用户点 Run workflow 就该收到邮件。"""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setattr(rg, "already_sent_today", lambda *a, **k: "run 999")
    code, calls, _, _ = run_main(monkeypatch, ["--send"], fake_collect())
    assert code == 0 and len(calls) == 1


def test_html_flag_writes_body(monkeypatch, tmp_path):
    out = tmp_path / "d.html"
    code, _, _, _ = run_main(monkeypatch, ["--dry", "--html", str(out)], fake_collect())
    assert code == 0 and out.read_text(encoding="utf-8").startswith("<html>")


# --- workflow 结构(防止改一处漏一处) ----------------------------------------
def test_workflow_is_wired_for_10am_beijing():
    wf = (Path(rg.__file__).parents[1] / ".github" / "workflows" / "rock-gd.yml").read_text(encoding="utf-8")
    assert "cron: '0 2 * * *'" in wf                                  # UTC 02:00 = 北京 10:00
    assert all(s in wf for s in ("MAIL_TO", "SMTP_USER", "SMTP_PASS"))
    assert "rock_gd.py --send" in wf


# --- 联网用例(默认跳过) -----------------------------------------------------
@pytest.mark.network
def test_live_scrape_returns_upcoming_events():
    evs, total, ok = rg.collect(rg.CITIES, 45)
    assert total > 0 and ok >= 1 and evs
    today = rg.now_cn().replace(hour=0, minute=0, second=0, microsecond=0)
    assert all(today <= rg.event_dt(e) <= today + rg.timedelta(days=45) for e in evs)


@pytest.mark.network
def test_live_cli_dry_run():
    r = subprocess.run([sys.executable, rg.__file__, "--dry", "--days", "20"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=180, check=False)
    assert r.returncode == 0 and "抓取" in r.stdout

