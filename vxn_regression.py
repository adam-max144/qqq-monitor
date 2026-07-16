#!/usr/bin/env python3
"""
vxn_regression.py - 基于 Wind/iFinD 导出的 VIX+VXN 历史数据，计算分段回归系数

用法:
  1. 从 Wind / 同花顺 iFinD 导出 VIX 和 VXN 的日线收盘价
     导出格式: CSV，至少包含 日期、VIX收盘、VXN收盘 三列
  2. 修改下方 CSV_PATH 路径
  3. python vxn_regression.py
  4. 脚本自动更新 index.html 和 fetch_vxn.py 中的系数
"""

import csv
import io
import os
import re
import sys
from datetime import datetime

# ========== 配置 ==========
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_HTML = os.path.join(REPO_DIR, "index.html")
FETCH_SCRIPT = os.path.join(REPO_DIR, "fetch_vxn.py")

# FRED 数据源（无需导出，直接下载）
FRED_VXN_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VXNCLS&cosd=2001-01-01"
FRED_VIX_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS&cosd=1990-01-01"

# === 如果不想从FRED下载，可以改为本地CSV路径 ===
CSV_PATH = os.path.join(REPO_DIR, "vix_vxn_data.csv")


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def fetch_from_fred():
    """直接从 FRED 下载 VIX 和 VXN 数据"""
    log("从 FRED 下载 VIX 数据...")
    vix = _download_fred_csv(FRED_VIX_URL)
    if not vix:
        return None, None
    log(f"   {len(vix)} 行")

    log("从 FRED 下载 VXN 数据...")
    vxn = _download_fred_csv(FRED_VXN_URL)
    if not vxn:
        return None, None
    log(f"   {len(vxn)} 行")

    # 按日期对齐
    vix_dict = dict(vix)
    vxn_dict = dict(vxn)
    common_dates = sorted(set(vix_dict.keys()) & set(vxn_dict.keys()))

    if not common_dates:
        log("❌ VIX 和 VXN 数据日期无重叠")
        return None, None

    vix_list = [vix_dict[d] for d in common_dates]
    vxn_list = [vxn_dict[d] for d in common_dates]
    log(f"   对齐后 {len(vix_list)} 个交易日 ({common_dates[0]} ~ {common_dates[-1]})")
    return vix_list, vxn_list


def _download_fred_csv(url):
    """下载 FRED CSV 并解析为 [(date, value), ...]"""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8")
    except Exception as e:
        log(f"  FRED 下载失败: {e}")
        return None

    reader = csv.reader(io.StringIO(text))
    next(reader)  # 表头
    data = []
    for row in reader:
        if len(row) >= 2 and row[1].strip():
            try:
                data.append((row[0].strip(), float(row[1])))
            except ValueError:
                continue
    return data


def load_data():
    """加载数据：优先 FRED 下载，回退本地 CSV"""
    vix_list, vxn_list = fetch_from_fred()
    if vix_list and len(vix_list) > 500:
        return vix_list, vxn_list

    log("FRED 下载失败，尝试本地 CSV...")
    if os.path.exists(CSV_PATH):
        return load_csv(CSV_PATH)

    log("本地 CSV 也不存在")
    return None, None


def load_csv(path):
    """从 CSV 加载 VIX 和 VXN 数据"""
    vix_list, vxn_list = [], []

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        log(f"CSV 列名: {header}")

        # 自动识别列
        vix_col = None
        vxn_col = None
        date_col = None
        for i, col in enumerate(header):
            col_upper = col.strip().upper()
            if "VIX" in col_upper and "VXN" not in col_upper:
                vix_col = i
            elif "VXN" in col_upper:
                vxn_col = i
            if "日期" in col_upper or "DATE" in col_upper:
                date_col = i

        if vix_col is None or vxn_col is None:
            log("❌ 未找到 VIX/VXN 列，请检查 CSV 列名")
            log(f"   需要包含 'VIX' 和 'VXN' 的列")
            return None, None

        log(f"   VIX 列: {header[vix_col]} (第{vix_col+1}列)")
        log(f"   VXN 列: {header[vxn_col]} (第{vxn_col+1}列)")

        for row in reader:
            if len(row) <= max(vix_col, vxn_col):
                continue
            try:
                vix = float(row[vix_col])
                vxn = float(row[vxn_col])
                if vix > 0 and vxn > 0:
                    vix_list.append(vix)
                    vxn_list.append(vxn)
            except (ValueError, IndexError):
                continue

    log(f"   加载 {len(vix_list)} 个交易日数据")
    return vix_list, vxn_list


def run_piecewise_regression(vix_list, vxn_list):
    """
    3段分段线性回归:
    Segment 1: VIX < 15
    Segment 2: 15 <= VIX < 25
    Segment 3: VIX >= 25
    """
    import numpy as np
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import r2_score

    vix = np.array(vix_list)
    vxn = np.array(vxn_list)

    results = {}

    # 各段回归
    segments = [
        ("低波 (<15)", vix < 15),
        ("正常 (15-25)", (vix >= 15) & (vix < 25)),
        ("高波 (≥25)", vix >= 25),
    ]

    all_pred = np.zeros_like(vix)
    overall_r2_list = []

    for name, mask in segments:
        count = np.sum(mask)
        if count < 10:
            results[name] = {"count": count, "a": 0, "b": 0, "r2": 0}
            continue

        X = vix[mask].reshape(-1, 1)
        y = vxn[mask]
        reg = LinearRegression(fit_intercept=True).fit(X, y)
        a, b = reg.intercept_, reg.coef_[0]
        r2 = r2_score(y, reg.predict(X))

        results[name] = {
            "count": int(count),
            "a": round(a, 4),
            "b": round(b, 4),
            "r2": round(r2, 4),
            "vix_mean": round(np.mean(vix[mask]), 2),
            "vxn_mean": round(np.mean(vxn[mask]), 2),
            "spread_mean": round(np.mean(vxn[mask] - vix[mask]), 2),
        }

        all_pred[mask] = reg.predict(X).flatten()

    # 整体 R²
    overall_r2 = round(r2_score(vxn, all_pred), 4)
    results["overall_r2"] = overall_r2

    # 边界值
    for boundary in [15, 25]:
        if "低波" in results and "正常" in results and boundary == 15:
            s1 = results["低波 (<15)"]
            s2 = results["正常 (15-25)"]
            v1 = s1["a"] + s1["b"] * boundary
            v2 = s2["a"] + s2["b"] * boundary
            results[f"boundary_{boundary}"] = {
                "seg1_pred": round(v1, 2),
                "seg2_pred": round(v2, 2),
                "jump": round(v2 - v1, 2),
            }
        if "正常" in results and "高波" in results and boundary == 25:
            s2 = results["正常 (15-25)"]
            s3 = results["高波 (≥25)"]
            v2 = s2["a"] + s2["b"] * boundary
            v3 = s3["a"] + s3["b"] * boundary
            results[f"boundary_{boundary}"] = {
                "seg2_pred": round(v2, 2),
                "seg3_pred": round(v3, 2),
                "jump": round(v3 - v2, 2),
            }

    return results


def print_results(results):
    """打印回归结果"""
    print()
    print("=" * 60)
    print("  分段线性回归结果")
    print("=" * 60)

    for name in ["低波 (<15)", "正常 (15-25)", "高波 (≥25)"]:
        if name not in results:
            continue
        r = results[name]
        print(f"\n  📊 {name}")
        print(f"     样本量: {r['count']}")
        print(f"     VXN = {r['a']:.4f} + {r['b']:.4f} × VIX")
        print(f"     R² = {r['r2']}")
        print(f"     VIX均值={r['vix_mean']}, VXN均值={r['vxn_mean']}, 平均偏移={r['spread_mean']}")

    print(f"\n  📈 整体 R² = {results.get('overall_r2', 'N/A')}")

    print(f"\n  ⚠️ 边界检查:")
    for b in [15, 25]:
        key = f"boundary_{b}"
        if key in results:
            r = results[key]
            print(f"     VIX={b}: 左段预测={r.get('seg1_pred',r.get('seg2_pred'))}, "
                  f"右段预测={r.get('seg2_pred',r.get('seg3_pred'))}, "
                  f"跳变={r['jump']}")

    print(f"\n  📋 对照表:")
    for vix_val in [10, 12, 14, 16, 18, 20, 22, 24, 26, 30, 35, 40]:
        # 判断属于哪一段
        if vix_val < 15:
            r = results.get("低波 (<15)", {})
        elif vix_val < 25:
            r = results.get("正常 (15-25)", {})
        else:
            r = results.get("高波 (≥25)", {})
        if r:
            pred = r["a"] + r["b"] * vix_val
            print(f"     VIX={vix_val:2d} → VXN≈{pred:.1f}")


def update_code(results):
    """更新 index.html 和 fetch_vxn.py 中的系数"""
    segs = [
        results.get("低波 (<15)", {}),
        results.get("正常 (15-25)", {}),
        results.get("高波 (≥25)", {}),
    ]

    if not all(segs):
        log("❌ 缺少分段数据，无法更新")
        return False

    # 生成 JS 代码
    js_code = f"""  const v=parseFloat(f[3]);if(isNaN(v)||v<=0)return null;
  // 3段线性回归（基于Wind/iFinD精确数据）
  let a,b;
  if(v<15){{a={segs[0]['a']:.3f};b={segs[0]['b']:.3f};}}
  else if(v<25){{a={segs[1]['a']:.3f};b={segs[1]['b']:.3f};}}
  else{{a={segs[2]['a']:.3f};b={segs[2]['b']:.3f};}}
  const vxn=a+b*v;"""

    # 更新 index.html
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        content = f.read()

    # 替换 parseVXN 中的计算逻辑
    old_pattern = re.compile(
        r"const v=parseFloat\(f\[3\]\);[^;]*?;\n"
        r"  // .*?\n"
        r"  let offset;[^;]*?;\n"
        r"  else if\(v<17\)offset[^;]*?;\n"
        r"  else if\(v<23\)offset[^;]*?;\n"
        r"  else if\(v<27\)offset[^;]*?;\n"
        r"  else offset[^;]*?;\n"
        r"  const vxn=v\+offset;",
        re.DOTALL
    )

    new_content = re.sub(old_pattern, js_code, content)

    if new_content == content:
        log("❌ index.html 替换失败（正则不匹配）")
        return False

    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(new_content)
    log(f"✅ 已更新 {INDEX_HTML}")

    # 更新 fetch_vxn.py
    py_code = f"""def estimate_vxn(vix):
    if vix < 15: a, b = {segs[0]['a']:.3f}, {segs[0]['b']:.3f}
    elif vix < 25: a, b = {segs[1]['a']:.3f}, {segs[1]['b']:.3f}
    else: a, b = {segs[2]['a']:.3f}, {segs[2]['b']:.3f}
    return round(a + b * vix, 1)"""

    with open(FETCH_SCRIPT, "r", encoding="utf-8") as f:
        content = f.read()

    py_old_pattern = re.compile(
        r"def estimate_vxn\(vix\):.*?return round\([^)]+\)",
        re.DOTALL
    )

    new_content = re.sub(py_old_pattern, py_code, content)

    if new_content == content:
        log("❌ fetch_vxn.py 替换失败")
        return False

    with open(FETCH_SCRIPT, "w", encoding="utf-8") as f:
        f.write(new_content)
    log(f"✅ 已更新 {FETCH_SCRIPT}")

    return True


def main():
    log("=" * 40)
    log("VXN 分段回归分析工具")
    log("=" * 40)

    # 检查 CSV
    if not os.path.exists(CSV_PATH):
        log(f"\n❌ 找不到 CSV 文件: {CSV_PATH}")
        log(f"\n请从 Wind / iFinD 导出数据:")
        log(f"  1. 打开 Wind/iFinD，搜索 VIX 和 VXN 指数")
        log(f"  2. 导出日线收盘价 (2006-2026)")
        log(f"  3. 保存为 CSV 文件到: {CSV_PATH}")
        log(f"  4. 重新运行此脚本")
        log(f"\nCSV 格式示例:")
        log(f"  日期,VIX收盘,VXN收盘")
        log(f"  2006-01-03,11.56,14.32")
        log(f"  2006-01-04,12.01,14.89")
        return 1

    vix_list, vxn_list = load_data()
    if vix_list is None or len(vix_list) < 100:
        log(f"❌ 数据不足 ({len(vix_list) if vix_list else 0}行)，需要至少100个交易日")
        return 1

    results = run_piecewise_regression(vix_list, vxn_list)
    print_results(results)

    log("\n正在更新代码文件...")
    if update_code(results):
        log("\n✅ 全部完成！记得 git commit 提交变更")
        log(f"   git add index.html fetch_vxn.py")
        log(f"   git commit -m \"update: VXN分段回归系数（基于Wind数据）\"")
        log(f"   git push")
    else:
        log("\n❌ 更新失败，请手动修改")

    return 0


if __name__ == "__main__":
    sys.exit(main())
