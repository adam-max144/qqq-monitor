#!/usr/bin/env python3
"""
update_vxn_model.py - 重新训练 VXN 回归模型系数

用法（需要能访问 Yahoo Finance 的网络）：
  python update_vxn_model.py

输出：
  - 打印新的回归系数
  - 自动更新 index.html 和 fetch_vxn.py 中的系数
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime

# ========== 配置 ==========
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_HTML = os.path.join(REPO_DIR, "index.html")
FETCH_SCRIPT = os.path.join(REPO_DIR, "fetch_vxn.py")


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def fetch_data():
    """从 Yahoo Finance 抓取 VIX 和 VXN 历史数据"""
    try:
        import yfinance as yf
    except ImportError:
        log("正在安装 yfinance...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "yfinance", "-q"]
        )
        import yfinance as yf

    log("下载 VIX 数据...")
    vix = yf.download("^VIX", start="2000-01-01", end=None, auto_adjust=True)
    log(f"  {len(vix)} 行")

    log("下载 VXN 数据...")
    vxn = yf.download("^VXN", start="2000-01-01", end=None, auto_adjust=True)
    log(f"  {len(vxn)} 行")

    import pandas as pd
    import numpy as np

    df = pd.DataFrame(
        {"VIX": vix["Close"], "VXN": vxn["Close"]}
    ).dropna()

    log(f"合并后 {len(df)} 个交易日")
    return df


def train_model(df):
    """训练线性回归模型"""
    import numpy as np
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import r2_score

    X = df["VIX"].values.reshape(-1, 1)
    y = df["VXN"].values

    # VXN = a + b * VIX
    reg = LinearRegression(fit_intercept=True).fit(X, y)
    a = reg.intercept_
    b = reg.coef_[0]
    r2 = r2_score(y, reg.predict(X))

    # 评估不同 VIX 区间的平均误差
    df["Pred"] = reg.predict(X)
    df["Error"] = df["Pred"] - df["VXN"]
    df["Regime"] = pd.cut(
        df["VIX"],
        bins=[0, 15, 25, 100],
        labels=["低波(<15)", "正常(15-25)", "高波(>25)"],
    )

    return a, b, r2, df


def update_html(a, b, r2):
    """更新 index.html 中的系数"""
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        content = f.read()

    # 更新 parseVXN 中的公式
    old_formula = r"const vxn=[\d.]+[\+\-\*][\d.]+[\*\w]*;"
    new_formula = f"const vxn={a:.3f}+{b:.3f}*v;"
    content = re.sub(old_formula, new_formula, content)

    # 更新注释中的公式和 R²
    old_comment = r"VXN = [\d.]+ \+ [\d.]+×VIX（20年线性回归 R²=[\d.]+）"
    new_comment = f"VXN = {a:.3f} + {b:.3f}×VIX（线性回归 R²={r2:.3f}）"
    content = re.sub(old_comment, new_comment, content)

    # 更新详情行
    old_detail = r"VXN≈.*?（[\d.]+[\+\-][\d.]+×VIX）"
    new_detail = f"VXN≈" + "'+(d.vix!=null?d.vix.toFixed(1):'N/A')+'" + f"（{a:.3f}+{b:.3f}×VIX）"
    # 这个比较复杂，用简单的字符串替换
    content = content.replace(
        "1.868+1.177×VIX",
        f"{a:.3f}+{b:.3f}×VIX",
    )

    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(content)

    log(f"已更新 {INDEX_HTML}")


def update_python(a, b):
    """更新 fetch_vxn.py 中的系数"""
    with open(FETCH_SCRIPT, "r", encoding="utf-8") as f:
        content = f.read()

    old = r"round\([\d.]+ \+ [\d.]+ \* vix, 1\)"
    new = f"round({a:.3f} + {b:.3f} * vix, 1)"
    content = re.sub(old, new, content)

    with open(FETCH_SCRIPT, "w", encoding="utf-8") as f:
        f.write(content)

    log(f"已更新 {FETCH_SCRIPT}")


def main():
    log("=" * 40)
    log("VXN 回归模型更新工具")
    log("=" * 40)

    try:
        df = fetch_data()
    except Exception as e:
        log(f"数据获取失败: {e}")
        log("提示：需要能访问 Yahoo Finance 的网络（VPN/海外）")
        return 1

    a, b, r2, df = train_model(df)

    log(f"\n=== 新回归系数 ===")
    log(f"VXN = {a:.3f} + {b:.3f} × VIX")
    log(f"R² = {r2:.4f}")
    log(f"数据量: {len(df)} 个交易日")

    log(f"\n=== 各区间误差 ===")
    for regime, group in df.groupby("Regime", observed=True):
        log(f"  {regime}: 平均误差 {group['Error'].mean():.3f}")

    log(f"\n=== 关键对照 ===")
    for vix_val in [10, 15, 20, 25, 30, 35, 40]:
        vxn_pred = a + b * vix_val
        log(f"  VIX={vix_val} → VXN≈{vxn_pred:.1f}")

    # 自动更新代码文件
    log(f"\n正在更新代码文件...")
    update_html(a, b, r2)
    update_python(a, b)

    log(f"\n✅ 完成！系数已更新到:")
    log(f"  - {INDEX_HTML}")
    log(f"  - {FETCH_SCRIPT}")
    log(f"记得 git commit 提交变更")

    return 0


if __name__ == "__main__":
    sys.exit(main())
