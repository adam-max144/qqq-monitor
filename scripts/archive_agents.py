"""归档同步脚本 — Hermes + Codex 数据镜像到 D:\\AI存档
用法: python scripts/archive_agents.py [--quiet]
- 复制运行目录 (C盘) → 存档目录 (D盘)，增量同步 (只覆盖变化的文件)
- 运行目录原位保留 (Hermes/Codex 依赖路径，不可移动)
- 排除: 锁文件、临时文件、git内部、音频/图片缓存、二进制程序
"""
import os, shutil, sys, time
from datetime import datetime

# ---------- 路径 ----------
HOME = os.path.expanduser("~")
HERMES = os.path.join(HOME, "AppData", "Local", "hermes")
CODEX = os.path.join(HOME, ".codex")
DEST = r"D:\AI存档"
QUIET = "--quiet" in sys.argv

# 每个来源 → (相对子目录, 源内相对路径列表)
PLAN = [
    ("Hermes", HERMES, [
        "memories", "skills", "cron",
        "config.yaml", "SOUL.md", "state.db",
    ]),
    ("Codex", CODEX, [
        "config.toml", "memories_1.sqlite", "history.jsonl",
        "sessions", "skills", "installation_id",
    ]),
    ("工作产物", r"D:\Desktop\qqq-monitor\backtest20y", [
        ".",  # 整个回测目录（脚本+数据+报告）
    ]),
    ("爬虫数据", r"D:\爬虫数据", ["."]),
]

# 复制时排除（按名称/后缀）
SKIP_NAMES = {".git", "__pycache__", ".jobs.lock", "tmp", "output"}
SKIP_EXTS = {".pyc", ".log", ".tmp", ".lock"}

def should_skip(name):
    if name in SKIP_NAMES:
        return True
    for e in SKIP_EXTS:
        if name.endswith(e):
            return True
    return False

def purge_excluded(dst_root):
    """清理目标目录中已不应存在的文件（历史残留，如早期复制过的 .lock）"""
    purged = 0
    for root, dirs, files in os.walk(dst_root):
        for f in files:
            if should_skip(f):
                p = os.path.join(root, f)
                try:
                    os.remove(p)
                    purged += 1
                except OSError:
                    pass
    return purged

def sync_tree(src, dst):
    """增量复制目录树，返回 (copied, skipped_files)"""
    copied = 0
    if not os.path.isdir(src):
        return copied
    os.makedirs(dst, exist_ok=True)
    for entry in os.listdir(src):
        s = os.path.join(src, entry)
        d = os.path.join(dst, entry)
        if should_skip(entry):
            continue
        if os.path.isdir(s):
            if entry == "sessions" and os.path.isdir(s):
                # 会话目录大且旧，只保留最近90天的子目录
                sync_sessions_recent(s, d)
            else:
                copied += sync_tree(s, d)
        else:
            try:
                s_m = os.path.getmtime(s)
                if os.path.exists(d) and abs(os.path.getmtime(d) - s_m) < 2:
                    continue  # 已是最新
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(s, d)
                copied += 1
            except OSError:
                pass
    return copied

def sync_sessions_recent(src, dst):
    """sessions 目录：按年/月归档，只同步最近90天内的会话"""
    os.makedirs(dst, exist_ok=True)
    cutoff = time.time() - 90 * 86400
    for root, dirs, files in os.walk(src):
        for f in files:
            p = os.path.join(root, f)
            if os.path.getmtime(p) < cutoff:
                continue
            rel = os.path.relpath(p, src)
            d = os.path.join(dst, rel)
            try:
                if os.path.exists(d) and abs(os.path.getmtime(d) - os.path.getmtime(p)) < 2:
                    continue
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(p, d)
            except OSError:
                pass

def main():
    t0 = time.time()
    report = []
    for label, src, items in PLAN:
        if not os.path.exists(src):
            report.append(f"  ⚠️ {label}: 源不存在 {src}")
            continue
        dst = os.path.join(DEST, label)
        n = 0
        for item in items:
            s = os.path.join(src, item)
            d = os.path.join(dst, item)
            if item == ".":
                n += sync_tree(src, dst)
            elif os.path.isdir(s):
                n += sync_tree(s, d)
            elif os.path.isfile(s):
                try:
                    if os.path.exists(d) and abs(os.path.getmtime(d) - os.path.getmtime(s)) < 2:
                        continue
                    os.makedirs(os.path.dirname(d), exist_ok=True)
                    shutil.copy2(s, d)
                    n += 1
                except OSError:
                    pass
        report.append(f"  {label}: {n} 文件")
    purged = purge_excluded(DEST)
    if purged:
        report.append(f"  清理残留: {purged} 文件")
    # 时间戳
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(os.path.join(DEST, "LAST_SYNC.txt"), "w", encoding="utf-8") as f:
        f.write(f"最后同步: {stamp}\n")
    if not QUIET:
        print(f"归档完成 ({time.time()-t0:.1f}s) @ {stamp}")
        print("\n".join(report))
        print(f"→ {DEST}")

if __name__ == "__main__":
    main()
