#!/usr/bin/env python3
"""
fetch_vxn.py - 从 FRED 获取 VXN 日线数据，更新 vxn.json 并推送至 GitHub

数据源:
  1. FRED VXNCLS (CBOE Nasdaq 100 Volatility Index, 官方日终结算价)
  2. 回退: 腾讯 VIX + 分段线性估算

用法:
  python fetch_vxn.py

Windows 定时任务: 每30分钟执行一次（FRED数据一般T+1更新）
"""

import csv
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError

# ========== 配置 ==========
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
VXN_JSON = os.path.join(REPO_DIR, "vxn.json")
LOG_FILE = os.path.join(REPO_DIR, "vxn_fetch.log")
FETCH_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# FRED 数据源（国内可访问，官方数据）
# 只取近期数据 + 回退到完整历史
FRED_VXN_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VXNCLS&cosd=2020-01-01"
FRED_VIX_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS&cosd=1990-01-01"
TENCENT_VIX_URL = "https://qt.gtimg.cn/q=usVIX"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ========== VXN 估算（腾讯 VIX 回退用） ==========
# 临时用平滑分段，待FRED数据精算后更新
def estimate_vxn(vix):
    if vix < 13:
        offset = 2.8
    elif vix < 17:
        offset = 2.8 + (vix - 13) / 4 * (4.5 - 2.8)
    elif vix < 23:
        offset = 4.5
    elif vix < 27:
        offset = 4.5 + (vix - 23) / 4 * (6.3 - 4.5)
    else:
        offset = 6.3
    return round(vix + offset, 1)


# ========== FRED 数据获取 ==========
def fetch_fred_csv(url):
    """从 FRED 下载 CSV 数据"""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        log(f"FRED 请求失败: {e}")
        return None


def parse_fred_csv(csv_text):
    """解析 FRED CSV，返回 (date, value) 列表"""
    reader = csv.reader(io.StringIO(csv_text))
    next(reader)  # 跳过表头
    data = []
    for row in reader:
        if len(row) >= 2 and row[1].strip():
            try:
                data.append((row[0].strip(), float(row[1])))
            except ValueError:
                continue
    return data


def get_latest_fred_vxn():
    """从 FRED 获取最新的 VXN 日线收盘价"""
    csv_text = fetch_fred_csv(FRED_VXN_URL)
    if not csv_text:
        return None, None

    data = parse_fred_csv(csv_text)
    if not data:
        return None, None

    # 取最新一条
    date, value = data[-1]
    log(f"FRED VXN: {value} ({date})")
    return value, date


def get_latest_fred_vix():
    """从 FRED 获取最新的 VIX 日线收盘价"""
    csv_text = fetch_fred_csv(FRED_VIX_URL)
    if not csv_text:
        return None, None

    data = parse_fred_csv(csv_text)
    if not data:
        return None, None

    date, value = data[-1]
    log(f"FRED VIX: {value} ({date})")
    return value, date


# ========== 腾讯 VIX 回退 ==========
def bytes_to_str(buf):
    b = bytearray(buf)
    s = ""
    for i in range(len(b)):
        s += chr(b[i])
    return s


def fetch_tencent_vix():
    """从腾讯 API 获取 VIX + 估算 VXN"""
    import re

    req = Request(TENCENT_VIX_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            html = bytes_to_str(resp.read())
            m = re.search(r'v_usVIX="(.*?)"', html)
            if not m:
                return None, None
            f = m.group(1).split("~")
            if len(f) < 4:
                return None, None
            vix = float(f[3])
            if vix <= 0:
                return None, None
            ts = f[30] if len(f) > 30 else ""
            vxn = estimate_vxn(vix)
            log(f"腾讯 VIX={vix} → VXN≈{vxn} (平滑分段估算)")
            return vxn, ts
    except Exception as e:
        log(f"腾讯 API 失败: {e}")
        return None, None


# ========== 更新 JSON ==========
def update_json(vxn, date, source):
    output = {
        "vxn": vxn,
        "date": date,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
    }
    with open(VXN_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    log(f"已写入 vxn.json: VXN = {vxn} ({source})")


# ========== Git 提交 ==========
def git_commit_and_push():
    try:
        result = subprocess.run(
            ["git", "diff", "--quiet", "vxn.json"],
            cwd=REPO_DIR, capture_output=True, timeout=10,
        )
        if result.returncode == 0:
            log("vxn.json 无变化，跳过提交")
            return True

        subprocess.run(
            ["git", "add", "vxn.json"],
            cwd=REPO_DIR, capture_output=True, timeout=10, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "auto: update VXN data"],
            cwd=REPO_DIR, capture_output=True, timeout=10, check=True,
        )

        env = os.environ.copy()
        env["GIT_SSL_BACKEND"] = "openssl"
        result = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=REPO_DIR, capture_output=True, timeout=30, env=env,
        )
        if result.returncode == 0:
            log("已推送到 GitHub")
            return True
        else:
            log(f"推送失败: {result.stderr.decode()[:200]}")
            return False
    except Exception as e:
        log(f"Git 异常: {e}")
        return False


# ========== 主流程 ==========
def main():
    log("=" * 40)
    log("获取 VXN 数据")

    # 1. FRED VXN（首选，官方日终结算价）
    vxn, date = get_latest_fred_vxn()
    source = "fred_vxncls"

    # 2. 回退：FRED VIX + 估算
    if vxn is None:
        log("FRED VXN 不可用，尝试 FRED VIX + 估算")
        vix, date = get_latest_fred_vix()
        if vix is not None:
            vxn = estimate_vxn(vix)
            source = "fred_vix+estimate"
            log(f" → VXN≈{vxn}")

    # 3. 最后回退：腾讯 VIX + 估算（国内直连）
    if vxn is None:
        log("FRED 不可用，回退腾讯 VIX + 估算")
        vxn, date = fetch_tencent_vix()
        source = "tencent_vix+estimate"

    if vxn is None:
        log("所有数据源均失败，保留现有 vxn.json")
        return 1

    update_json(vxn, date, source)

    if git_commit_and_push():
        log("完成")
        return 0
    else:
        log("本地已更新，推送待重试")
        return 0


if __name__ == "__main__":
    sys.exit(main())
