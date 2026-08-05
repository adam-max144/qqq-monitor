"""场内纳指基金自动扫描脚本（GitHub Actions版）
数据源（全部实测可用，无第三方依赖）:
- 腾讯批量行情 qt.gtimg.cn: 现价/昨收/成交额/总市值/名称
- 天天基金 pingzhongdata: 官方单位净值序列 + 净值日（QDII净值滞后T+2）
- 新浪美股日K: QQQ/SPY 收盘，用于把披露溢价校正为真实溢价
- 费用/成立/经理: 静态配置（2026-08-03 从天天基金App接口逐只验证）
输出: monitor.html（场内纳指基金监控页）
"""
import urllib.request, json, re, time
from datetime import datetime

# 监控标的（场内QDII ETF，全部纯美股指数、无A股；仅保留纳斯达克100）
# code: [市场 sh/sz, 指数类别, 管理费%, 托管费%, 是否核心推荐, 备注]
FUNDS = {
    "159632": ["sz", "纳指100", 0.60, 0.20, True,  "⭐主力·当前溢价最低的大规模纳指"],
    "513300": ["sh", "纳指100", 0.60, 0.20, True,  "⭐主力·规模/流动性/品牌最佳"],
    "513100": ["sh", "纳指100", 0.60, 0.20, False, "老牌最大·溢价全场最贵"],
    "159941": ["sz", "纳指100", 0.80, 0.20, False, "规模最大·溢价最贵"],
    "513110": ["sh", "纳指100", 0.80, 0.20, False, "溢价低·费率偏高"],
    "513390": ["sh", "纳指100", 0.50, 0.15, False, "费率最低"],
    "159659": ["sz", "纳指100", 0.50, 0.15, False, ""],
    "159696": ["sz", "纳指100", 0.50, 0.10, False, "费率最低档"],
    "159501": ["sz", "纳指100", 0.50, 0.10, False, ""],
    "513870": ["sh", "纳指100", 0.50, 0.10, False, ""],
}
INDEX_US = {"纳指100": "QQQ"}  # 真实溢价校正用

def fetch(url, ref, tries=3, enc="utf-8"):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": ref})
            return urllib.request.urlopen(req, timeout=20).read().decode(enc, "ignore")
        except Exception as e:
            last = e
            time.sleep(1.0 * (i + 1))
    raise last

# ---------- 1. 腾讯批量行情 ----------
def fetch_quotes():
    syms = ",".join(("sh" if m == "sh" else "sz") + c for c, m in
                    ((c, FUNDS[c][0]) for c in FUNDS))
    raw = fetch("https://qt.gtimg.cn/q=" + syms, "https://gu.qq.com/", enc="gbk")
    out = {}
    for line in raw.strip().split(";"):
        line = line.strip()
        if "=" not in line or "~" not in line:
            continue
        p = line.split("~")
        if len(p) < 60:
            continue
        code = p[2]
        try:
            out[code] = {
                "name": p[1].replace("ETF", "ETF"),
                "price": float(p[3]),
                "prev": float(p[4]),
                "amount_yi": float(p[37]) / 10000.0,   # 成交额(万)->亿
                "mcap_yi": float(p[45]),               # 总市值(亿)
            }
        except (ValueError, IndexError):
            continue
    return out

# ---------- 2. 天天基金净值序列 ----------
def fetch_nav(code):
    raw = fetch(f"https://fund.eastmoney.com/pingzhongdata/{code}.js",
                "https://fund.eastmoney.com/")
    m = re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", raw, re.DOTALL)
    if not m:
        return {}, None, None
    trend = json.loads(m.group(1))
    nav_map = {}
    for p in trend:
        d = datetime.utcfromtimestamp(p["x"] / 1000).strftime("%Y-%m-%d")
        nav_map[d] = p["y"]
    dates = sorted(nav_map.keys())
    return nav_map, dates[-1] if dates else None, nav_map[dates[-1]] if dates else None

# ---------- 3. 腾讯日K（场内价，算近期涨跌和20日均溢价） ----------
def fetch_kline(sym):
    raw = fetch(f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,45,qfq",
                "https://gu.qq.com/")
    d = json.loads(raw)
    k = d["data"][sym]
    days = k.get("qfqday") or k.get("day") or []
    return {row[0]: float(row[2]) for row in days}

# ---------- 4. 美股日K（QQQ/SPY 校正） ----------
def fetch_us_kline(sym):
    url = (f"https://stock.finance.sina.com.cn/usstock/api/jsonp_v2.php/"
           f"var%20_{sym}_=/US_MinKService.getDailyK?symbol={sym}&___qn=30")
    raw = fetch(url, "https://finance.sina.com.cn/")
    m = re.search(r"\((.*)\)", raw, re.DOTALL)
    if not m:
        return {}
    data = json.loads(m.group(1))
    return {row["d"]: float(row["c"]) for row in data if isinstance(row, dict) and "d" in row}

# ---------- 主流程 ----------
quotes = fetch_quotes()
print(f"行情获取: {len(quotes)}/{len(FUNDS)} 只")

us_closes = {idx: fetch_us_kline(sym) for idx, sym in INDEX_US.items()}

results = []
for code, (market, index, mgmt, trust, core, note) in FUNDS.items():
    rec = {"code": code, "market": market, "index": index, "mgmt": mgmt, "trust": trust,
           "core": core, "note": note, "ok": False}
    try:
        q = quotes.get(code)
        if not q:
            print(f"  ⚠️ {code} 无行情")
            results.append(rec)
            continue
        nav_map, nav_date, nav_last = fetch_nav(code)
        kline = fetch_kline(market + code)
        rec["name"] = q["name"]
        rec["price"] = q["price"]
        rec["prev"] = q["prev"]
        rec["chg_pct"] = (q["price"] / q["prev"] - 1) * 100 if q["prev"] else None
        rec["amount_yi"] = q["amount_yi"]
        rec["mcap_yi"] = q["mcap_yi"]

        # 近5日涨跌
        dates5 = sorted(kline.keys())
        if len(dates5) >= 6 and dates5[-6] in kline:
            rec["chg5_pct"] = (q["price"] / kline[dates5[-6]] - 1) * 100
        else:
            rec["chg5_pct"] = None

        # 披露溢价（官方净值口径，含T+2滞后）
        if nav_last:
            rec["nav_date"] = nav_date
            rec["nav"] = nav_last
            rec["prem_pct"] = (q["price"] / nav_last - 1) * 100
        else:
            rec["prem_pct"] = None

        # 真实溢价 = 现价/(净值 × (1 + 美股区间涨幅)) - 1，区间 = 净值日→美股最新交易日
        # qqq_base 是净值日当天的 QQQ 收盘价，浏览器端实时层用它 + 实时QQQ 重算真实溢价
        rec["qqq_base"] = None
        if nav_date and nav_date in us_closes.get(index, {}):
            us = us_closes[index]
            us_dates = sorted(us.keys())
            last_us_date = us_dates[-1]
            rec["qqq_base"] = us[nav_date]
            if last_us_date > nav_date:
                chg_us = us[last_us_date] / us[nav_date] - 1
                rec["prem_true_pct"] = (q["price"] / (nav_last * (1 + chg_us)) - 1) * 100
                rec["us_chg"] = chg_us * 100
                rec["us_note"] = f"{nav_date}→{last_us_date} {chg_us*100:+.1f}%"
        if "prem_true_pct" not in rec:
            rec["prem_true_pct"] = rec["prem_pct"]
            rec["us_note"] = "未校正"

        # 20日均溢价（price/NAV 同日对齐，取最近20个有数据的交易日）
        prems = []
        for date in sorted(kline.keys())[-25:]:
            if date in nav_map:
                prems.append((kline[date] / nav_map[date] - 1) * 100)
        rec["prem20"] = (sum(prems[-20:]) / len(prems[-20:])) if prems else None
        rec["ok"] = True
    except Exception as e:
        print(f"  ⚠️ {code} 处理失败: {e}")
    results.append(rec)
    time.sleep(0.15)

# 排序：核心推荐在前，其余按真实溢价升序
cores = [r for r in results if r["core"]]
others = [r for r in results if not r["core"]]
others.sort(key=lambda r: (r.get("prem_true_pct") if r.get("prem_true_pct") is not None else 999))
results_sorted = cores + others

def pct_str(v, nd=2, sign=False):
    if v is None:
        return "--"
    s = f"{v:+.{nd}f}%" if sign else f"{v:.{nd}f}%"
    return s

def color_prem(v):
    if v is None:
        return "flat"
    if v < 5:
        return "ok"
    if v <= 8:
        return "warn"
    return "bad"

def chg_cls(v):
    if v is None:
        return "flat"
    if v > 0.05:
        return "up"
    if v < -0.05:
        return "down"
    return "flat"

def card(r):
    prem_c = color_prem(r.get("prem_pct"))
    fee = f"{r['mgmt']:.2f}%+{r['trust']:.2f}%"
    lines = f"""
    <div class="fund{' core' if r['core'] else ''}" data-c="{r['code']}">
      <div class="hdr"><b>{r.get('name','?')}</b>
        <span><span class="cd">{r['code']}</span><span class="tag idx">{r['index']}</span>{'<span class="tag core">核心</span>' if r['core'] else ''}</span>
      </div>
      <div class="rw">
        <div class="bx"><div class="lb">现价</div><div class="vl v-price">{r.get('price','--')}</div></div>
        <div class="bx"><div class="lb">今日涨跌</div><div class="vl v-chg {chg_cls(r.get('chg_pct'))}">{pct_str(r.get('chg_pct'), sign=True)}</div></div>
        <div class="bx"><div class="lb">披露溢价</div><div class="vl v-prem {prem_c}">{pct_str(r.get('prem_pct'))}</div></div>
        <div class="bx"><div class="lb">真实溢价</div><div class="vl v-premt {prem_c}">{pct_str(r.get('prem_true_pct'))}</div></div>
      </div>
      <div class="rw">
        <div class="bx"><div class="lb">近5日</div><div class="vl v-chg5 {chg_cls(r.get('chg5_pct'))}">{pct_str(r.get('chg5_pct'), sign=True)}</div></div>
        <div class="bx"><div class="lb">费用(管理+托管)</div><div class="vl">{fee}</div></div>
        <div class="bx"><div class="lb">规模</div><div class="vl v-mcap">{r.get('mcap_yi','--')}亿</div></div>
        <div class="bx"><div class="lb">日成交</div><div class="vl v-amt">{f"{r['amount_yi']:.2f}" if r.get('amount_yi') is not None else '--'}亿</div></div>
      </div>
      <div class="inf">20日均溢价 <b>{pct_str(r.get('prem20'))}</b> · 净值日 {r.get('nav_date','--')} · 真实溢价校正 {r.get('us_note','')} · {r.get('note','')}<span class="v-live"></span></div>
    </div>"""
    return lines

now = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
ok_n = sum(1 for r in results if r["ok"])

# ---------- 浏览器端实时层：把快照值改造成数据，页面打开后实时覆盖 ----------
meta = {}
for r in results:
    if not r.get("ok"):
        continue
    meta[r["code"]] = {
        "market": r["market"], "name": r.get("name", ""),
        "nav": r.get("nav"), "navDate": r.get("nav_date"),
        "qqqBase": r.get("qqq_base"),
        "prem20": r.get("prem20"), "usNote": r.get("us_note", ""),
        "note": r.get("note", ""), "core": bool(r.get("core")),
    }
meta_js = json.dumps(meta, ensure_ascii=False)

# ---------- 持仓管理: 017436 主仓(净值/限购/跟踪偏差) + 黄金/纳指/蓄水池管道 ----------
pos = {"ok": False}
try:
    raw = fetch("https://fund.eastmoney.com/pingzhongdata/017436.js", "https://fund.eastmoney.com/")
    m = re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", raw, re.DOTALL)
    trend = json.loads(m.group(1))
    nav_map = {datetime.utcfromtimestamp(p["x"] / 1000).strftime("%Y-%m-%d"): p["y"] for p in trend}
    ds = sorted(nav_map)
    def ret_at(anchor):
        for d in ds:
            if d >= anchor:
                return (nav_map[ds[-1]] / nav_map[d] - 1) * 100
        return None
    qq = us_closes.get("纳指100", {})
    qds = sorted(qq)
    qqq_ytd = None
    for d in qds:
        if d >= "2026-01-01":
            qqq_ytd = (qq[qds[-1]] / qq[d] - 1) * 100
            break
    limit = None
    try:
        jj = fetch("http://fundf10.eastmoney.com/jjgg_017436_4.html", "https://fundf10.eastmoney.com/")
        lm = re.search(r"单日累计购买上限[^<]*?(\d+)\s*(元|万|百|千)?", jj)
        if lm:
            num, unit = int(lm.group(1)), lm.group(2) or "元"
            if unit == "万": num *= 10000
            elif unit == "百": num *= 100
            elif unit == "千": num *= 1000
            limit = num
        elif "暂停" in jj:
            limit = 0
    except Exception:
        pass
    pos = {"nav": nav_map[ds[-1]], "navDate": ds[-1], "limit": limit,
           "ytd": ret_at("2026-01-01"), "qqqYtd": qqq_ytd, "ok": True}
    print(f"017436: 净值 {pos['nav']} ({pos['navDate']}) 限购 {limit} YTD {pos['ytd']:.1f}% vs QQQ {qqq_ytd:.1f}%")
except Exception as e:
    print(f"  ⚠️ 017436 持仓数据失败: {e}")

POSITION_META = {
    "fund": {"code": "017436", "name": "华宝纳指精选A",
             "nav": pos.get("nav") if pos.get("ok") else None,
             "navDate": pos.get("navDate") if pos.get("ok") else None,
             "limit": pos.get("limit") if pos.get("ok") else None,
             "ytd": pos.get("ytd") if pos.get("ok") else None,
             "qqqYtd": pos.get("qqqYtd") if pos.get("ok") else None},
    "gold": {"code": "518880", "name": "黄金ETF华安", "market": "sh"},
    "ndx": {"code": "159632", "name": "纳斯达克ETF华安", "market": "sz"},
    "cash": {"code": "511880", "name": "银华日利ETF", "market": "sh"},
}
pos_js = json.dumps(POSITION_META, ensure_ascii=False)

RT_JS = r'''
// ===== 实时行情层 =====
// 数据源: 腾讯行情 qt.gtimg.cn (Access-Control-Allow-Origin: *, 浏览器可直接fetch)
// 字段: p[3]现价 p[4]昨收 p[32]涨跌幅% p[37]成交额(万) p[45]总市值(亿) p[63]近5日% p[77]溢价率%(现价/最新净值-1) p[81]腾讯最新净值
// 真实溢价: 现价/(快照净值 × (1 + 实时QQQ/净值日QQQ收盘 - 1)) - 1，逻辑与每日快照完全一致，仅把静态值换成实时值
const META = FUND_META;
const INTERVAL = 60000;                 // 每60秒刷新一次
const SYMS = Object.keys(META).map(c => META[c].market + c).join(',') + ',usQQQ,sh518880,sh511880';
const $ = s => document.querySelector(s);
const usOpen = () => {                   // 美股盘中(美东周一~五 9:30-16:00) → 用腾讯实时价; 否则用昨收(=最新收盘)
  const d = new Date();
  const n = new Date(d.toLocaleString('en-US', {timeZone: 'America/New_York'}));
  const h = n.getHours() + n.getMinutes() / 60, w = n.getDay();
  return w >= 1 && w <= 5 && h >= 9.5 && h < 16;
};
const pct = (v, nd, sign) => (v == null || !isFinite(v)) ? '--' : (sign && v > 0 ? '+' : '') + v.toFixed(nd) + '%';
const premCls = v => (v == null || !isFinite(v)) ? 'flat' : (v < 5 ? 'ok' : (v <= 8 ? 'warn' : 'bad'));
const chgCls = v => (v == null || !isFinite(v)) ? 'flat' : (v > 0.05 ? 'up' : (v < -0.05 ? 'down' : 'flat'));
function set(el, sel, txt, cls) {
  const v = el.querySelector(sel);
  if (!v) return;
  v.textContent = txt;
  if (cls) v.className = 'vl ' + cls;
}
async function refresh() {
  const rt = $('#rt');
  if (!rt) return;
  try {
    const r = await fetch('https://qt.gtimg.cn/q=' + SYMS, {cache: 'no-store'});
    const buf = await r.arrayBuffer();
    let txt;
    try { txt = new TextDecoder('gbk').decode(buf); } catch (e) { txt = new TextDecoder().decode(buf); }
    const rows = {};
    for (const seg of txt.split(';')) {
      const m = seg.match(/v_([A-Za-z0-9.]+)="([^"]*)"/);
      if (!m) continue;
      const p = m[2].split('~');
      if (p.length < 40) continue;
      rows[p[2]] = p;
    }
    const qq = rows['QQQ.OQ'];
    const qqqLive = qq ? parseFloat(usOpen() ? qq[3] : qq[4]) : null;
    let n = 0, missing = 0;
    for (const code in META) {
      const f = META[code], p = rows[code];
      const el = document.querySelector('.fund[data-c="' + code + '"]');
      if (!el) continue;
      if (!p) { el.classList.add('stale'); missing++; continue; }
      const price = parseFloat(p[3]), prev = parseFloat(p[4]);
      if (!isFinite(price) || !isFinite(prev)) { el.classList.add('stale'); missing++; continue; }
      const chg = (price / prev - 1) * 100;
      const chg5 = parseFloat(p[63]);
      const amt = parseFloat(p[37]) / 10000;
      const mcap = parseFloat(p[45]);
      const tprem = parseFloat(p[77]);                        // 腾讯披露溢价(最新净值口径) f77
      let prem = isFinite(tprem) ? tprem : (f.nav ? (price / f.nav - 1) * 100 : null);
      let premt = null;
      if (f.qqqBase && qqqLive && f.nav) {                    // 有校正基准 → 用实时QQQ重算真实溢价
        const qr = qqqLive / f.qqqBase - 1;
        premt = (price / (f.nav * (1 + qr)) - 1) * 100;
      }
      if (premt == null) premt = prem;                        // 未校正 → 与披露溢价一致
      set(el, '.v-price', price.toFixed(3));
      set(el, '.v-chg', pct(chg, 2, true), chgCls(chg));
      set(el, '.v-chg5', pct(chg5, 2, true), chgCls(chg5));
      set(el, '.v-prem', pct(prem), premCls(prem));
      set(el, '.v-premt', pct(premt), premCls(premt));
      if (isFinite(amt)) set(el, '.v-amt', amt.toFixed(2) + '亿');
      if (isFinite(mcap)) set(el, '.v-mcap', mcap.toFixed(2) + '亿');
      const live = el.querySelector('.v-live');
      if (live) {
        let s = ' · 🟢 实时';
        if (f.nav && isFinite(parseFloat(p[81])) && Math.abs(parseFloat(p[81]) - f.nav) > f.nav * 0.001) {
          s += ' · 腾讯净值已更新至 ' + p[81];
        }
        live.textContent = s;
      }
      el.classList.remove('stale');
      n++;
    }
    const t = new Date();
    updatePos(rows, qqqLive);
    rt.textContent = '🟢 实时 ' + t.toTimeString().slice(0, 8) + ' · ' + n + '/' + Object.keys(META).length + '只'
      + (qqqLive ? ' · QQQ ' + qqqLive.toFixed(2) : '') + (missing ? ' · ⚠️' + missing + '只无数据' : '') + ' · 60s自动刷新·点击手动';
    rt.className = 'ok';
  } catch (e) {
    rt.textContent = '⚪ 实时获取失败·显示每日快照·点此重试';
    rt.className = 'bad';
  }
}
// ===== 持仓管理(方案: 017436主仓 + 518880黄金弹药 + 159632抄底 + 511880蓄水池) =====
const P = POSITION_META;
const LS = k => localStorage.getItem(k);
function setPos(sel, txt, cls) {
  const el = document.querySelector(sel);
  if (!el) return;
  el.textContent = txt;
  if (cls) el.className = 'vl ' + cls;
}
function updatePos(rows, qqqLive) {
  const f = P.fund;
  if (f.nav != null) {
    setPos('.v-pnav', f.nav.toFixed(4));
    setPos('.v-pnavd', f.navDate);
    setPos('.v-plimit', f.limit == null ? '--' : f.limit === 0 ? '暂停' : '¥' + (f.limit >= 1000 ? (f.limit / 1000) + 'K' : f.limit) + '/日');
    const gap = (f.ytd != null && f.qqqYtd != null) ? f.ytd - f.qqqYtd : null;
    if (gap != null) {
      setPos('.v-pgap', (gap > 0 ? '+' : '') + gap.toFixed(1) + 'pp', gap < -10 ? 'bad' : gap < -5 ? 'warn' : gap < 0 ? 'flat' : 'ok');
      const tr = document.getElementById('p-track');
      if (tr) tr.textContent = 'YTD ' + f.ytd.toFixed(1) + '% vs QQQ ' + f.qqqYtd.toFixed(1) + '% · 主动型, 连续两季跑输>10pp换标的';
    }
  }
  const g = rows['518880'];
  if (g) {
    const price = parseFloat(g[3]), chg = parseFloat(g[32]), prem = parseFloat(g[77]);
    setPos('.v-gprice', price.toFixed(3));
    setPos('.v-gchg', (chg > 0 ? '+' : '') + chg.toFixed(2) + '%', chg > 0.05 ? 'up' : chg < -0.05 ? 'down' : 'flat');
    setPos('.v-gprem', isFinite(prem) ? prem.toFixed(2) + '%' : '--', premCls(prem));
    const cost = parseFloat(LS('posGoldCost')), sh = parseInt(LS('posGoldShares'));
    const el = document.getElementById('p-gold');
    if (cost > 0 && sh > 0) {
      const dd = (1 - price / cost) * 100, mv = price * sh;
      setPos('.v-gdd', (dd > 0 ? '+' : '') + dd.toFixed(1) + '%', dd >= 25 ? 'bad' : dd >= 15 ? 'warn' : 'ok');
      el.textContent = '成本 ' + cost.toFixed(3) + ' · 市值 ¥' + Math.round(mv) + ' · ' +
        (dd >= 25 ? '🔴 DD>25% 清仓→买纳指' : dd >= 15 ? '🟡 DD>15% 卖半仓→买纳指' : '🟢 弹药就位');
    } else {
      setPos('.v-gdd', '--');
      el.textContent = '点 ✏️设置 录入黄金成本价与份额';
    }
  }
  const n = rows['159632'];
  if (n && qqqLive) {
    const price = parseFloat(n[3]), f2 = META['159632'];
    const qr = qqqLive / f2.qqqBase - 1;
    const premt = (price / (f2.nav * (1 + qr)) - 1) * 100;
    setPos('.v-nprice', price.toFixed(3));
    setPos('.v-nprem', premt.toFixed(2) + '%', premt < 2 ? 'ok' : premt < 5 ? 'warn' : 'bad');
    setPos('.v-np20', f2.prem20 != null ? f2.prem20.toFixed(1) + '%' : '--');
    document.getElementById('p-ndx').textContent = premt < 2 ? '🟢 真实溢价<2% 可用蓄水池买入' : '🔴 真实溢价' + premt.toFixed(1) + '% ≥2% 等待 (触发线<2%)';
  }
  const c = rows['511880'];
  if (c) {
    setPos('.v-cprice', parseFloat(c[3]).toFixed(3));
    const init = parseFloat(LS('posCashInit')) || 0, used = parseFloat(LS('posCashUsed')) || 0;
    const el = document.getElementById('p-cash');
    if (init > 0) {
      setPos('.v-cbal', '¥' + Math.round(init - used).toLocaleString());
      el.textContent = '剩余 ¥' + Math.round(init - used).toLocaleString() + ' / ' + Math.round(init).toLocaleString() + ' · 等触发: 纳指溢价<2% 或 DD>15%';
    } else {
      setPos('.v-cbal', '--');
      el.textContent = '点 ✏️设置 录入蓄水池初始金额';
    }
  }
}
function posEdit() {
  const q = (label, cur) => prompt(P.fund.name + ' 持仓设置\n' + label, cur || '');
  const c = q('黄金成本价(元/份, 如 8.64)', LS('posGoldCost'));
  if (c != null && c !== '') localStorage.setItem('posGoldCost', c);
  const s = q('黄金份额(份)', LS('posGoldShares'));
  if (s != null && s !== '') localStorage.setItem('posGoldShares', s);
  const i = q('蓄水池初始金额(元)', LS('posCashInit'));
  if (i != null && i !== '') localStorage.setItem('posCashInit', i);
  const u = q('已投入金额(元, 默认0)', LS('posCashUsed') || '0');
  if (u != null && u !== '') localStorage.setItem('posCashUsed', u);
  refresh();
}
refresh();
setInterval(refresh, INTERVAL);
$('#rt').onclick = refresh;
'''

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>场内纳指基金监控</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,sans-serif;background:#0d1117;color:#e6edf3;padding:16px;max-width:500px;margin:0 auto}}
h1{{font-size:20px;font-weight:700}}
.sub{{font-size:11px;color:#8b949e;margin:4px 0 14px}}
#rt{{cursor:pointer;font-weight:700}}
#rt.ok{{color:#3fb950}} #rt.bad{{color:#f85149}}
.fund{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:14px;margin-bottom:10px}}
.fund.core{{border-color:#238636;background:linear-gradient(135deg,#12221a,#161b22)}}
.fund.stale{{opacity:.45}}
.hdr{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:6px}}
.hdr b{{font-size:13px;line-height:1.4}}
.hdr span{{display:flex;align-items:center;gap:4px;flex-shrink:0}}
.cd{{font-size:10px;color:#8b949e;background:#21262d;padding:2px 6px;border-radius:4px}}
.tag{{font-size:9px;padding:2px 5px;border-radius:4px;font-weight:700}}
.tag.idx{{background:#001a3d;color:#58a6ff}}
.tag.core{{background:#002d1a;color:#3fb950}}
.rw{{display:flex;gap:6px;margin-top:6px}}
.bx{{flex:1;padding:6px 4px;border-radius:6px;text-align:center;background:#0d1117;border:1px solid #21262d;min-width:0}}
.bx .lb{{color:#8b949e;font-size:9px}}
.bx .vl{{font-weight:700;font-size:12px;margin-top:2px;white-space:nowrap}}
.ok{{color:#3fb950}} .warn{{color:#d29922}} .bad{{color:#f85149}} .flat{{color:#8b949e}}
.up{{color:#3fb950}} .down{{color:#f85149}}
.inf{{font-size:10px;color:#8b949e;margin-top:6px;line-height:1.5}}
.v-live{{color:#3fb950}}
.hdr2{{font-size:13px;font-weight:700;margin:14px 0 6px;padding:6px 0;border-bottom:1px solid #21262d}}
.pos-edit{{float:right;font-size:10px;font-weight:400;color:#58a6ff;cursor:pointer;border:1px solid #30363d;border-radius:6px;padding:1px 8px}}
.note{{margin-top:14px;padding:10px;background:#1c2128;border-radius:8px;font-size:10px;color:#8b949e;line-height:1.6;border:1px solid #21262d}}
</style>
</head>
<body>
<h1>📡 场内纳指基金监控</h1>
<p class="sub">每日快照 {now} · 共{ok_n}/{len(FUNDS)}只 · <span id="rt">🟢 实时行情加载中…</span><br>浏览器实时抓取腾讯行情(60s自动刷新) · GitHub Actions每日更新官方净值</p>
<div class="hdr2">📊 持仓管理 <span class="pos-edit" onclick="posEdit()">✏️ 设置</span></div>
<div id="pos">
  <div class="fund">
    <div class="hdr"><b>017436 华宝纳指精选A</b><span><span class="cd">主仓·场外定投</span></span></div>
    <div class="rw">
      <div class="bx"><div class="lb">最新净值</div><div class="vl v-pnav">--</div></div>
      <div class="bx"><div class="lb">净值日</div><div class="vl v-pnavd">--</div></div>
      <div class="bx"><div class="lb">日限购</div><div class="vl v-plimit">--</div></div>
      <div class="bx"><div class="lb">跟踪偏差</div><div class="vl v-pgap">--</div></div>
    </div>
    <div class="inf" id="p-track">每周¥1K按净值定投 · 零溢价 · QDII净值T+1更新(快照)</div>
  </div>
  <div class="fund">
    <div class="hdr"><b>518880 黄金ETF华安</b><span><span class="cd">弹药·场内T+0</span></span></div>
    <div class="rw">
      <div class="bx"><div class="lb">现价</div><div class="vl v-gprice">--</div></div>
      <div class="bx"><div class="lb">今日涨跌</div><div class="vl v-gchg">--</div></div>
      <div class="bx"><div class="lb">溢价</div><div class="vl v-gprem">--</div></div>
      <div class="bx"><div class="lb">浮亏DD</div><div class="vl v-gdd">--</div></div>
    </div>
    <div class="inf" id="p-gold">点 ✏️设置 录入黄金成本价与份额</div>
  </div>
  <div class="fund">
    <div class="hdr"><b>159632 纳斯达克ETF华安</b><span><span class="cd">抄底·场内</span></span></div>
    <div class="rw">
      <div class="bx"><div class="lb">现价</div><div class="vl v-nprice">--</div></div>
      <div class="bx"><div class="lb">真实溢价</div><div class="vl v-nprem">--</div></div>
      <div class="bx"><div class="lb">触发线</div><div class="vl"> &lt;2% </div></div>
      <div class="bx"><div class="lb">20日均</div><div class="vl v-np20">--</div></div>
    </div>
    <div class="inf" id="p-ndx">用蓄水池等溢价窗口</div>
  </div>
  <div class="fund">
    <div class="hdr"><b>511880 银华日利</b><span><span class="cd">蓄水池·场内</span></span></div>
    <div class="rw">
      <div class="bx"><div class="lb">现价</div><div class="vl v-cprice">--</div></div>
      <div class="bx"><div class="lb">余额</div><div class="vl v-cbal">--</div></div>
      <div class="bx"><div class="lb">状态</div><div class="vl">货币ETF</div></div>
      <div class="bx"><div class="lb">年化</div><div class="vl">~1.8%</div></div>
    </div>
    <div class="inf" id="p-cash">点 ✏️设置 录入蓄水池初始金额</div>
  </div>
</div>
<div class="hdr2">⭐ 核心推荐</div>
<div id="list">{''.join(card(r) for r in cores if r.get('ok'))}</div>
<div class="hdr2">📋 全部场内纳斯达克100 ETF（按真实溢价升序）</div>
{''.join(card(r) for r in results_sorted)}
<div class="note">
<strong>📐 口径说明</strong><br>
• <b>披露溢价</b> = 现价/最新官方净值 - 1（QDII净值滞后T+2，会偏高）<br>
• <b>真实溢价</b> = 现价/(净值×(1+美股区间涨幅)) - 1，用QQQ把净值日→最新交易日的美股涨幅扣除<br>
• <b>20日均溢价</b> = 近20个交易日 场内价/同日净值 均值，判断当前贵不贵（每日快照更新）<br>
• 费用 = 管理费+托管费（静态配置，2026-08-03从天天基金App逐只核实）<br>
• 场内ETF无申购限额，但溢价是隐性成本：&lt;5%可买，5-8%谨慎，&gt;8%建议等回落或换标的<br>
• ⚠️ 若QDII额度恢复、限购解除，溢价会快速收敛，高溢价买入部分将直接受损
</div>
<script>const FUND_META = {meta_js};const POSITION_META = {pos_js};const SNAP_TIME = "{now}";</script>
<script>{RT_JS}</script>
</body>
</html>"""

with open("monitor.html", "w", encoding="utf-8") as f:
    f.write(html)
print(f"✅ monitor.html 已生成（{ok_n}只成功）")
