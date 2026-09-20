"""net.py(退避重试) / cn_calendar.py(A股交易日) / crawl.upsert_csv(同日去重) 的离线回归用例。

全部不联网: net 的重试语义用本地假 HTTP 服务端计数来判定(不看日志、不看 exit code)。
"""
from __future__ import annotations

import datetime as dt
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import net
import pytest


# ------------------------------------------------------------------ net.py
@pytest.fixture()
def flaky_server():
    """前 2 次 503、第 3 次 200;/gone 恒 404。判据 = 服务端收到的请求次数。"""
    hits = {"flaky": 0, "gone": 0}

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_GET(self):
            if self.path == "/flaky":
                hits["flaky"] += 1
                code = 503 if hits["flaky"] < 3 else 200
                body = b"bad" if code == 503 else f"OK-{hits['flaky']}".encode()
            else:
                hits["gone"] += 1
                code, body = 404, b"nope"
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):  # 静音
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", hits
    srv.shutdown()


def test_net_retries_transient_503(flaky_server):
    base, hits = flaky_server
    assert net.fetch(base + "/flaky") == "OK-3"
    assert hits["flaky"] == 3                      # 退避重试确实发生


def test_net_does_not_retry_404(flaky_server):
    base, hits = flaky_server
    with pytest.raises(urllib.error.HTTPError):
        net.fetch(base + "/gone")
    assert hits["gone"] == 1                       # ⚠️ HTTPError ⊂ URLError, 4xx 不能一锅端重试


def test_is_retryable_semantics():
    assert net._is_retryable(net.TransientHTTP(503, "u"))
    assert net._is_retryable(urllib.error.HTTPError("u", 503, "be", {}, None))
    assert not net._is_retryable(urllib.error.HTTPError("u", 404, "nf", {}, None))
    assert not net._is_retryable(ValueError("逻辑错不该重试"))


def test_parse_retry_after():
    assert net.parse_retry_after("3") == 3
    assert net.parse_retry_after(None) is None
    assert net.parse_retry_after("junk") is None
    assert net.parse_retry_after("9999") == net.MAX_WAIT    # 有上限, 不被对方拖住


# ------------------------------------------------------------------ cn_calendar
def test_cn_holidays_2026():
    cn = pytest.importorskip("cn_calendar")
    if not cn.HAVE_HOLIDAYS:
        pytest.skip("未安装 holidays")
    for d in (dt.date(2026, 2, 17), dt.date(2026, 10, 1), dt.date(2026, 9, 25)):  # 春节/国庆/中秋
        assert not cn.is_trading_day("cn", d), d
    assert cn.is_trading_day("cn", dt.date(2026, 9, 18))      # 普通周五
    assert not cn.is_trading_day("cn", dt.date(2026, 9, 20))  # 周日


def test_cn_makeup_weekend_is_not_trading_day():
    """调休补班的周六日交易所不开市 —— 不能拿 holidays 的 workday 反推。"""
    cn = pytest.importorskip("cn_calendar")
    if not cn.HAVE_HOLIDAYS:
        pytest.skip("未安装 holidays")
    for d in (dt.date(2025, 2, 8), dt.date(2025, 1, 26)):
        assert not cn.is_trading_day("cn", d), f"{d} 是调休上班日, 但交易所不开市"


def test_cn_today_is_beijing_not_local():
    cn = pytest.importorskip("cn_calendar")
    bj = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
    assert cn.today_cn() == bj                    # CI runner 是 UTC, 必须固定 +08:00


# ------------------------------------------------------------------ crawl.upsert_csv
def test_upsert_csv_replaces_same_day(tmp_path):
    crawl = pytest.importorskip("crawl")
    p = tmp_path / "518880.csv"
    hdr = ["时间", "名称", "现价"]
    assert crawl.upsert_csv(p, hdr, ["2026-08-22 10:00:00", "黄金ETF", 9.1]) == 0
    assert crawl.upsert_csv(p, hdr, ["2026-08-22 15:00:00", "黄金ETF", 9.2]) == 1   # 同日 → 覆盖
    assert crawl.upsert_csv(p, hdr, ["2026-08-23 10:00:00", "黄金ETF", 9.3]) == 0
    text = p.read_text(encoding="utf-8-sig")
    assert text.count("2026-08-22") == 1          # 不再堆重复日期
    assert "9.2" in text and "9.1" not in text    # 保留最新一条
    assert text.count("2026-08-23") == 1          # 不同日正常追加
    assert text.startswith("时间,名称,现价")       # 表头只一份
