#!/usr/bin/env python3
"""
fetch_vxn.py - 从 Yahoo Finance 获取 ^VXN 实时数据，更新 vxn.json 并推送至 GitHub

安装：
  1. 确保 Python 3 已安装且 pip install yfinance（或使用 urllib 原生）
  2. Windows 任务计划程序：每 30 分钟执行一次

用法：
  python fetch_vxn.py
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError

# ========== 配置 ==========
REPO_DIR = os.path.dirname(os.path.abspath(__file__))  # qqq_web 目录
VXN_JSON = os.path.join(REPO_DIR, "vxn.json")
LOG_FILE = os.path.join(REPO_DIR, "vxn_fetch.log")
FETCH_TIMEOUT = 15  # 秒
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
# 腾讯 API（国内可访问，作为回退）
TENCENT_VIX_URL = "https://qt.gtimg.cn/q=usVIX"
# 平滑分段: 低波+2.8/正常+4.5/高波+6.3，过渡区线性插值
def estimate_vxn(vix):
    if vix < 13: offset = 2.8
    elif vix < 17: offset = 2.8 + (vix - 13) / 4 * (4.5 - 2.8)
    elif vix < 23: offset = 4.5
    elif vix < 27: offset = 4.5 + (vix - 23) / 4 * (6.3 - 4.5)
    else: offset = 6.3
    return round(vix + offset, 1)



def log(msg):
    """写日志"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def fetch_vxn_yahoo():
    """从 Yahoo Finance v8 API 获取 ^VXN 最新价格"""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVXN?interval=1d&range=1d"
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})

    try:
        with urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except URLError as e:
        log(f"Yahoo 请求失败: {e.reason}")
        return None, None
    except Exception as e:
        log(f"Yahoo 解析失败: {e}")
        return None, None

    try:
        result = data.get("chart", {}).get("result", [{}])[0]
        meta = result.get("meta", {})

        # 优先取 regularMarketPrice（当前/最后成交价）
        price = meta.get("regularMarketPrice")
        ts = meta.get("regularMarketTime")

        # 回退：从报价数据中找最后一个非空 close
        if price is None:
            quotes = result.get("indicators", {}).get("quote", [{}])[0]
            closes = quotes.get("close", [])
            timestamps = result.get("timestamp", [])
            for i in range(len(closes) - 1, -1, -1):
                if closes[i] is not None:
                    price = closes[i]
                    ts = timestamps[i] if i < len(timestamps) else None
                    break

        # 最后回退：昨日收盘
        if price is None:
            price = meta.get("chartPreviousClose")
            ts = None

        if price is not None:
            return round(price, 2), ts
        else:
            log("Yahoo 返回数据中无有效价格")
            return None, None

    except Exception as e:
        log(f"Yahoo 数据提取失败: {e}")
        return None, None


def bytes_to_str(buf):
    """腾讯API返回的GBK编码字节转字符串"""
    b = bytearray(buf)
    s = ""
    for i in range(len(b)):
        s += chr(b[i])
    return s


def parse_tencent_vix(html):
    """解析腾讯API的 VIX 数据，返回 VIX 值和时间戳"""
    import re
    m = re.search(r'v_usVIX="(.*?)"', html)
    if not m:
        return None, None
    f = m.group(1).split("~")
    if len(f) < 4:
        return None, None
    try:
        v = float(f[3])
    except (ValueError, IndexError):
        return None, None
    if v <= 0:
        return None, None
    ts = f[30] if len(f) > 30 else ""
    return v, ts


def fetch_vix_tencent():
    """从腾讯 API 获取 VIX 数据，返回 VXN ≈ VIX + 3.5"""
    req = Request(TENCENT_VIX_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            raw = resp.read()
            html = bytes_to_str(raw)
            vix, ts = parse_tencent_vix(html)
            if vix is not None:
                vxn = estimate_vxn(vix)
                log(f"腾讯 VIX={vix} → VXN≈{vxn}（平滑分段）")
                return vxn, ts
            else:
                log("腾讯 VIX 解析失败")
                return None, None
    except Exception as e:
        log(f"腾讯 API 请求失败: {e}")
        return None, None


def update_json(price, timestamp):
    """更新 vxn.json"""
    output = {
        "vxn": price,
        "timestamp": timestamp,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "yahoo_finance_^VXN",
    }
    with open(VXN_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    log(f"已写入 vxn.json: VXN = {price}")


def git_commit_and_push():
    """提交并推送 vxn.json 到 GitHub"""
    try:
        # 检查是否有变更
        result = subprocess.run(
            ["git", "diff", "--quiet", "vxn.json"],
            cwd=REPO_DIR,
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            log("vxn.json 无变化，跳过提交")
            return True

        # Stage
        subprocess.run(
            ["git", "add", "vxn.json"],
            cwd=REPO_DIR,
            capture_output=True,
            timeout=10,
            check=True,
        )

        # Commit
        subprocess.run(
            ["git", "commit", "-m", "auto: update VXN data"],
            cwd=REPO_DIR,
            capture_output=True,
            timeout=10,
            check=True,
        )

        # Push
        env = os.environ.copy()
        env["GIT_SSL_BACKEND"] = "openssl"
        result = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=REPO_DIR,
            capture_output=True,
            timeout=30,
            env=env,
        )

        if result.returncode == 0:
            log("已推送到 GitHub")
            return True
        else:
            log(f"推送失败: {result.stderr.decode()[:200]}")
            return False

    except subprocess.TimeoutExpired:
        log("Git 操作超时")
        return False
    except subprocess.CalledProcessError as e:
        log(f"Git 操作失败: {e.stderr.decode()[:200] if e.stderr else e}")
        return False
    except Exception as e:
        log(f"Git 异常: {e}")
        return False


def main():
    log("=" * 40)
    log("开始获取 VXN 数据")

    # 优先 Yahoo（海外数据源，需科学上网才能连）
    price, timestamp = fetch_vxn_yahoo()

    # 回退：腾讯 VIX + 3.5（国内可直连）
    if price is None:
        log("Yahoo 不可达，回退到腾讯 VIX+3.5 估算")
        price, timestamp = fetch_vix_tencent()

    if price is None:
        log("所有数据源均失败，保留现有 vxn.json")
        return 1

    update_json(price, timestamp)

    if git_commit_and_push():
        log("完成，已推送到 GitHub Pages")
        return 0
    else:
        log("本地 vxn.json 已更新，但推送失败（下次定时任务会重试）")
        return 0


if __name__ == "__main__":
    sys.exit(main())
