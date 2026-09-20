# -*- coding: utf-8 -*-
"""crawl.py — 简易爬虫命令行工具（数据自动整理到 D:\\爬虫数据）

用法:
  python scripts/crawl.py quote QQQ,518880,159632   # 腾讯行情(自动加市场前缀, 可多只逗号分隔)
  python scripts/crawl.py nav 017436                # 东财基金净值(最近5条, 按日期去重追加)
  python scripts/crawl.py limit 017436              # 东财限购公告(追加历史)
  python scripts/crawl.py fetch <url> [gbk]         # 通用抓取存到 D:/爬虫数据/fetch/<站点>/
  python scripts/crawl.py dedupe [目录]             # 数据体检: 清掉历史 CSV 里的重复日期行

数据目录（可用环境变量 CRAWL_DATA 覆盖，默认 D:\\爬虫数据）:
  quote\\<代码>.csv    行情历史: 时间,名称,现价,昨收,涨跌%,溢价%
  nav\\<代码>.csv      净值历史: 日期,净值,日涨跌%
  limit\\<代码>.csv    限购历史: 时间,限购
  fetch\\<站点>\\<日期>_<时间>.txt   通用抓取原文

依赖: 标准库即可(net.py 自带退避重试; 装了 tenacity 会自动用 tenacity 后端)；全部站点已验证，无需登录。
⚠️ 追加写按**日期 upsert**: 同一天重跑会覆盖当天旧行, 不再堆重复日期(2026-09-20 实测 limit/015299 与 quote/518880 都出现过同日两行)。
"""
import json
import os
import re
import sys
from datetime import datetime

from net import fetch as net_fetch      # 带退避重试的取数(scripts/net.py)

DATA_DIR = os.environ.get("CRAWL_DATA", r"D:\爬虫数据")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fetch(url, ref=None, enc="utf-8", timeout=15):
    """取数(带指数退避+抖动重试, 只重试瞬时错误) —— 实现见 scripts/net.py"""
    return net_fetch(url, ref, enc, timeout=timeout, headers=UA)


def tx_sym(code):
    """腾讯行情代码补前缀: QQQ→usQQQ, 51/56/58开头→sh, 15/16/18开头→sz"""
    c = code.strip().upper()
    if c[:2] == "US" or not c.isdigit():
        return c if c[:2] == "US" else "us" + c
    return ("sh" if c[0] == "5" else "sz") + c


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def append_csv(path, header, row):
    """UTF-8 BOM 追加，Excel 可直接打开；新文件先写表头"""
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        if new:
            f.write(",".join(header) + "\n")
        f.write(",".join(str(x) for x in row) + "\n")


def upsert_csv(path, header, row):
    """按**日期** upsert: 同日已有行则替换(保留最新一次), 避免重跑堆重复日期。

    返回被替换掉的行数(便于调用方打印)。key 取 row[0] 的日期部分(前 10 字符, "YYYY-MM-DD")。
    """
    key = str(row[0])[:10]
    body, dropped = [], 0
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
        for line in lines[1:]:                       # 跳表头
            if not line.strip():
                continue
            if line.split(",")[0][:10] == key:
                dropped += 1
            else:
                body.append(line)
    body.append(",".join(str(x) for x in row))
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(",".join(header) + "\n")
        f.write("\n".join(body) + "\n")
    return dropped


def cmd_quote(syms):
    r = fetch("https://qt.gtimg.cn/q=" + ",".join(tx_sym(s) for s in syms), "https://gu.qq.com/", "gbk")
    outdir = ensure_dir(os.path.join(DATA_DIR, "quote"))
    for seg in r.split(";"):
        m = re.search(r'v_([A-Za-z0-9.]+)="([^"]*)"', seg)
        if not m:
            continue
        p = m[2].split("~")
        if len(p) <= 40:
            continue
        prem = p[77] if len(p) > 77 and p[77] else "--"
        path = os.path.join(outdir, p[2] + ".csv")
        dup = upsert_csv(path, ["时间", "名称", "现价", "昨收", "涨跌%", "溢价%"],
                         [now(), p[1], p[3], p[4], p[32], prem])
        print(f"{p[2]:10s} {p[1]:8s} 现价={p[3]:>10} 涨跌={p[32]}% 溢价={prem}%"
              f"{'  (覆盖同日旧行)' if dup else ''}  → {path}")


def cmd_nav(code, n=5):
    url = f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize={n}"
    d = fetch(url, "https://fundf10.eastmoney.com/")
    data = json.loads(d)
    rows = data.get("Data", {}).get("LSJZList", [])
    outdir = ensure_dir(os.path.join(DATA_DIR, "nav"))
    path = os.path.join(outdir, code + ".csv")
    seen = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            next(f, None)  # 跳表头
            for line in f:
                if line.strip():
                    seen.add(line.split(",")[0])
    for x in rows:
        if x["FSRQ"] not in seen:
            append_csv(path, ["日期", "净值", "日涨跌%"], [x["FSRQ"], x["DWJZ"], x.get("JZZZL", "--")])
        print(f"{x['FSRQ']}  净值 {x['DWJZ']}  日涨跌 {x.get('JZZZL', '--')}%  → {path}")


def cmd_limit(code):
    t = fetch(f"http://fundf10.eastmoney.com/jjgg_{code}_4.html", "https://fundf10.eastmoney.com/")
    m = re.search(r"单日累计购买上限[^<]*?(\d+)\s*(元|万|百|千)?", t)
    if m:
        num, unit = int(m.group(1)), m.group(2) or "元"
        if unit == "万":
            num *= 10000
        elif unit == "百":
            num *= 100
        elif unit == "千":
            num *= 1000
        outdir = ensure_dir(os.path.join(DATA_DIR, "limit"))
        path = os.path.join(outdir, code + ".csv")
        dup = upsert_csv(path, ["时间", "限购(元)"], [now(), num])
        print(f"{code} 限购: {num} 元/日{'  (覆盖同日旧行)' if dup else ''}  → {path}")
    else:
        print("未找到限购字段(可能公告页面变动)")


def cmd_fetch(url, enc="utf-8"):
    t = fetch(url, enc=enc)
    host = re.sub(r"[^0-9a-zA-Z]", "_", url.split("/")[2]) if "//" in url else "unknown"
    outdir = ensure_dir(os.path.join(DATA_DIR, "fetch", host))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(outdir, ts + ".txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(t)
    with open(os.path.join(outdir, "_latest.txt"), "w", encoding="utf-8") as f:
        f.write(t)
    print(f"已保存 {len(t)} 字符 → {path}")


def cmd_dedupe(root=None):
    """数据体检: 清掉历史 CSV 里的重复日期行(同一天保留**最后**一条), 幂等。"""
    root = root or DATA_DIR
    n_files = n_dups = 0
    for sub in ("quote", "limit", "nav"):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith(".csv"):
                continue
            path = os.path.join(d, name)
            with open(path, encoding="utf-8-sig") as f:
                lines = f.read().splitlines()
            if not lines:
                continue
            header, body = lines[0], [ln for ln in lines[1:] if ln.strip()]
            seen, keep = set(), []
            for line in reversed(body):                 # 倒序遍历 → 同日保留最后出现的那条
                k = line.split(",")[0][:10]
                if k in seen:
                    continue
                seen.add(k)
                keep.append(line)
            keep.reverse()
            dups = len(body) - len(keep)
            n_files += 1
            if dups:
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    f.write(header + "\n" + "\n".join(keep) + "\n")
                n_dups += dups
                print(f"  {sub}/{name}: 去掉重复日期 {dups} 行 → 剩 {len(keep)} 行")
    print(f"扫描 {n_files} 个 CSV, 清理重复日期 {n_dups} 行" + ("(无重复, 干净)" if not n_dups else ""))


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return
    cmd = args[0]
    if cmd == "quote":
        cmd_quote(args[1].split(",") if len(args) > 1 else ["QQQ"])
    elif cmd == "nav" and len(args) > 1:
        cmd_nav(args[1])
    elif cmd == "limit" and len(args) > 1:
        cmd_limit(args[1])
    elif cmd == "fetch" and len(args) > 1:
        cmd_fetch(args[1], args[2] if len(args) > 2 else "utf-8")
    elif cmd == "dedupe":
        cmd_dedupe(args[1] if len(args) > 1 else None)
    else:
        print("参数错误。用法见: python scripts/crawl.py --help")


if __name__ == "__main__":
    main()
