"""net.py — 全仓库统一的「带退避重试」取数工具。

为什么要它: 本机/CI 长期踩间歇性断流 —— 东财 push2his 连打十几次后整段 RemoteDisconnected、
腾讯行情偶发超时、GitHub 连接被掐。此前每个脚本各写一套 `for i in range(tries)` 朴素重试,
没有退避、没有抖动、也不看状态码(4xx 也会白重试)。

设计:
  · **tenacity 可选**: 装了就用 `retry_if_exception(_is_retryable)` + `wait_exponential_jitter` + `reraise`;
    没装则走等价的内置实现(退避曲线一致), 所以 CI 不加依赖也不会坏。
  · **只重试瞬时错误**: 连接类异常 + 408/429/5xx。⚠️ 4xx 一律不重试 —— 注意
    `urllib.error.HTTPError` 是 `URLError` 的子类, 直接按 URLError 重试会把 404 也重试满。
  · 默认 4 次机会、1→2→4s 退避 + 抖动(防惊群)。

用法:
    from net import fetch, fetch_bytes
    txt  = fetch(url, ref="https://gu.qq.com/", enc="gbk", timeout=20)   # 文本
    data = fetch_bytes(url, timeout=30)                                  # 原始字节

命令行:
    python scripts/net.py <url> [--ref URL] [--enc gbk] [--show 200] [--tries 4]
"""

from __future__ import annotations

import random
import sys
import time
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):          # Windows 控制台默认 GBK
    sys.stdout.reconfigure(encoding="utf-8")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
RETRY_STATUS = (408, 429, 500, 502, 503, 504)
DEFAULT_TRIES = 4
BASE_WAIT = 1.0
MAX_WAIT = 20.0

try:                                            # tenacity 可选
    from tenacity import (
        retry,
        retry_if_exception,
        stop_after_attempt,
        wait_exponential_jitter,
    )
    HAVE_TENACITY = True
except ImportError:                             # pragma: no cover - 环境差异
    HAVE_TENACITY = False


class TransientHTTP(Exception):
    """可重试的 HTTP 状态(408/429/5xx)。"""

    def __init__(self, status: int, url: str):
        super().__init__(f"HTTP {status} (transient) {url}")
        self.status = status


def _is_retryable(exc: BaseException) -> bool:
    """瞬时错误才重试; 4xx 立刻放弃(HTTPError ⊂ URLError, 不能一锅端)。"""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in RETRY_STATUS
    if isinstance(exc, TransientHTTP):
        return True
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError, OSError))


def parse_retry_after(value: str | None) -> float | None:
    """429/503 常见 Retry-After: N(秒)。给个上限, 免得对方让等一小时。"""
    if not value:
        return None
    try:
        return min(float(value.strip()), MAX_WAIT)
    except (TypeError, ValueError):
        return None


def fetch_bytes(url: str, ref: str | None = None, timeout: float = 20,
                tries: int = DEFAULT_TRIES, headers: dict | None = None) -> bytes:
    """取原始字节; 失败抛原始异常(不包装)。"""
    h = {"User-Agent": UA}
    if ref:
        h["Referer"] = ref
    if headers:
        h.update(headers)

    def _once() -> bytes:
        req = urllib.request.Request(url, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:  # 站点均为 http(s)
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in RETRY_STATUS:
                raise TransientHTTP(e.code, url) from e
            raise

    if HAVE_TENACITY:
        fn = retry(stop=stop_after_attempt(tries),
                   wait=wait_exponential_jitter(initial=BASE_WAIT, max=MAX_WAIT, jitter=1),
                   retry=retry_if_exception(_is_retryable),
                   reraise=True)(_once)
        return fn()

    # 内置等价实现(无 tenacity 时): 指数退避 + 抖动, 只重试可重试错误
    delay = BASE_WAIT
    for attempt in range(1, tries + 1):
        try:
            return _once()
        except Exception:
            if attempt >= tries:
                raise
            time.sleep(delay + random.uniform(0, 1))  # 抖动, 非加密用途
            delay = min(delay * 2, MAX_WAIT)
    raise AssertionError("unreachable")  # pragma: no cover


def fetch(url: str, ref: str | None = None, enc: str = "utf-8", timeout: float = 20,
          tries: int = DEFAULT_TRIES, headers: dict | None = None) -> str:
    """取文本, 按 enc 解码(东财部分页面是 gbk), 坏字节忽略。"""
    return fetch_bytes(url, ref, timeout, tries, headers).decode(enc, "ignore")


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="带退避重试的取数(tenacity 可选)")
    ap.add_argument("url")
    ap.add_argument("--ref")
    ap.add_argument("--enc", default="utf-8")
    ap.add_argument("--tries", type=int, default=DEFAULT_TRIES)
    ap.add_argument("--show", type=int, default=0)
    a = ap.parse_args()
    txt = fetch(a.url, a.ref, a.enc, tries=a.tries)
    print(f"backend={'tenacity' if HAVE_TENACITY else 'builtin'} | {len(txt)} 字符 / "
          f"{len(txt.encode('utf-8'))} 字节")
    if a.show:
        print(txt[: a.show])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
