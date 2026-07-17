#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QQQ 加仓建议网站 — Flask 服务器
iPhone/手机浏览器直接访问
"""

import json
import urllib.request
import re
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request
import threading

app = Flask(__name__)

# ========== 数据源 ==========
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17 like Mac OS X) AppleWebKit/605.1.15',
}
SINA_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://finance.sina.com.cn',
}
TIMEOUT = 20

# ========== 策略参数 ==========
BASE_UNIT = 2000  # 每期定投基准（元）
VIX_THRESHOLDS = {'complacent': 15, 'normal': 20, 'elevated': 25, 'fearful': 30, 'very_fearful': 40}
DD_THRESHOLDS  = {'normal': 5, 'dip': 10, 'correction': 15, 'deep': 20}

# ========== 缓存 ==========
_cache = {"data": None, "time": None, "lock": threading.Lock()}

# ========== 工具 ==========
def fetch(url, headers=HEADERS):
    try:
        req = urllib.request.Request(url, headers=headers)
        raw = urllib.request.urlopen(req, timeout=TIMEOUT).read()
        for enc in ('utf-8', 'gbk', 'gb2312'):
            try: return raw.decode(enc)
            except: continue
        return raw.decode('utf-8', errors='replace')
    except: return None

def to_float(s):
    if not s or s in ('-','','--'): return None
    try: return float(s.strip().replace(',',''))
    except: return None

# ========== 数据获取 ==========
def fetch_qqq():
    text = fetch('https://qt.gtimg.cn/q=usQQQ')
    if not text: return None
    m = re.search(r'v_usQQQ="(.*?)"', text)
    if not m: return None
    f = m.group(1).split('~')
    if len(f) < 68: return None
    price, high52 = to_float(f[3]), to_float(f[48])
    if not price or not high52: return None
    return {'price': price, 'high52': high52, 'name': f[1], 'time': f[30]}

def fetch_vix():
    text = fetch('https://qt.gtimg.cn/q=usVIX')
    if text:
        m = re.search(r'v_usVIX="(.*?)"', text)
        if m:
            f = m.group(1).split('~')
            if len(f) > 3:
                v = to_float(f[3])
                t = f[30] if len(f) > 30 else ''
                stale = False
                if t:
                    try:
                        stale = (datetime.now() - datetime.strptime(t, '%Y-%m-%d %H:%M:%S')).days > 1
                    except: stale = True
                if v and v > 0: return v, stale, t
    text = fetch('https://hq.sinajs.cn/list=gb_vix', headers=SINA_HEADERS)
    if text:
        m = re.search(r'var hq_str_gb_vix="(.*?)"', text)
        if m:
            f = m.group(1).split(',')
            if len(f) > 1 and f[0]:
                v = to_float(f[1])
                if v and v > 0: return v, False, ''
    return None, False, ''

# ========== 评分决策 ==========
def score_vix(v):
    if v is None: return 0
    if v < VIX_THRESHOLDS['complacent']: return -1
    if v < VIX_THRESHOLDS['normal']: return 0
    if v < VIX_THRESHOLDS['elevated']: return 1
    if v < VIX_THRESHOLDS['fearful']: return 2
    if v < VIX_THRESHOLDS['very_fearful']: return 3
    return 4

def score_dd(dd):
    if dd is None: return 0
    if dd < DD_THRESHOLDS['normal']: return 0
    if dd < DD_THRESHOLDS['dip']: return 1
    if dd < DD_THRESHOLDS['correction']: return 2
    if dd < DD_THRESHOLDS['deep']: return 3
    return 4

def get_action(total, dd):
    SCORE_MAP = [
        (9, 3.0, '🚀 重仓出击',   '全力加仓，备用资金上场'),
        (7, 2.0, '✅ 积极布局',   '正常加仓，可加大力度'),
        (5, 1.5, '📈 适度加仓',   '按档位执行加仓计划'),
        (3, 1.0, '📊 常规操作',   '正常定投+小幅加仓'),
        (1, 0.5, '🔍 谨慎试探',   '仅基础定投，不加码'),
        (-9, 0.0,'⛔ 停止加仓',   '观望为主，不追加资金'),
    ]
    mult, label, detail = 0, '等待', ''
    for t, m, l, d in SCORE_MAP:
        if total >= t: mult, label, detail = m, l, d; break
    if dd is not None and dd < 5:
        mult = min(mult, 0.5)
    return mult, label, detail

def analyze():
    """获取数据→评分→结论，返回完整字典"""
    q = fetch_qqq()
    if not q: return {'error': 'QQQ数据获取失败'}
    v, v_stale, v_time = fetch_vix()
    dd = ((q['high52'] - q['price']) / q['high52']) * 100
    
    vs = score_vix(v)
    ds = score_dd(dd)
    total = vs + ds + 0  # PE跳过=0
    mult, label, detail = get_action(total, dd)
    amount = int(BASE_UNIT * mult)
    
    # VIX文字说明
    if v is None: vix_desc = '数据不可用'
    elif v < 15:  vix_desc = '市场自满，注意风险'
    elif v < 20:  vix_desc = '正常水平，观望'
    elif v < 25:  vix_desc = '小幅恐慌，关注机会'
    elif v < 30:  vix_desc = '恐慌区间，逢低布局'
    elif v < 40:  vix_desc = '极度恐慌，加仓良机'
    else:         vix_desc = '极端恐慌，别人恐惧我贪婪'
    
    # 回撤文字
    if dd < 5:    dd_desc = '正常波动，不加仓'
    elif dd < 10: dd_desc = '小幅回调，可试探性小加'
    elif dd < 15: dd_desc = '调整区间，执行加仓'
    elif dd < 20: dd_desc = '深度调整，积极布局'
    else:         dd_desc = '极端下跌，重仓出击'
    
    # 颜色
    if total >= 5: color = '#2e7d32'  # 绿
    elif total >= 1: color = '#f57c00'  # 橙
    else: color = '#c62828'  # 红
    
    return {
        'price': q['price'],
        'high52': q['high52'],
        'drawdown': round(dd, 1),
        'vix': v,
        'vix_desc': vix_desc,
        'vix_stale': v_stale,
        'vix_time': v_time,
        'dd_desc': dd_desc,
        'vix_score': vs,
        'dd_score': ds,
        'total_score': total,
        'max_score': 10,  # VIX最大4 + DD最大4 + PE最大2 = 10
        'signal': label,
        'detail': detail,
        'multiplier': mult,
        'amount': amount,
        'base_unit': BASE_UNIT,
        'color': color,
        'update_time': q['time'],
        'check_time': datetime.now().strftime('%H:%M:%S'),
    }

# ========== 路由 ==========
@app.route('/')
def index():
    result = analyze()
    return render_template('index.html', data=result, data_json=json.dumps(result, ensure_ascii=False))

@app.route('/refresh')
def refresh():
    return jsonify(analyze())

# ========== 启动 ==========
if __name__ == '__main__':
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except:
        ip = '127.0.0.1'
    s.close()
    print(f'🚀 QQQ加仓建议站 已启动')
    print(f'📱 iPhone (同WiFi): http://{ip}:5050')
    print(f'💻 本机访问:        http://127.0.0.1:5050')
    print(f'⏹  停止: Ctrl+C')
    app.run(host='0.0.0.0', port=5050, debug=False, threaded=True)
