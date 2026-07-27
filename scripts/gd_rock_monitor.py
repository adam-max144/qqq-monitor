#!/usr/bin/env python3
"""
广东省摇滚演出监控 — GitHub Actions 版
数据源：搜狗微信搜索（可用的唯一数据源）
"""
import json, urllib.request, urllib.parse, re, ssl, smtplib
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime, timezone, timedelta

now = datetime.now(timezone(timedelta(hours=8)))
CUTOFF = now + timedelta(days=180)

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}

def fetch(url):
    try:
        req = urllib.request.Request(url, headers=H)
        resp = urllib.request.urlopen(req, timeout=20, context=ctx)
        return resp.read().decode('utf-8', errors='replace')
    except: return None

def parse_date(text):
    """从文本提取日期"""
    # 匹配 04/24 或 4月10日 或 2026-03-11 或 3月2日
    patterns = [
        (r'(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})', lambda y,m,d: datetime(int(y),int(m),int(d),tzinfo=timezone(timedelta(hours=8)))),
        (r'(\d{1,2})[月](\d{1,2})[日]', lambda m,d: datetime(now.year,int(m),int(d),tzinfo=timezone(timedelta(hours=8)))),
        (r'(\d{1,2})[-./](\d{1,2})', lambda m,d: datetime(now.year,int(m),int(d),tzinfo=timezone(timedelta(hours=8)))),
    ]
    for pat, fn in patterns:
        m = re.search(pat, text)
        if m:
            try:
                dt = fn(*m.groups())
                # 如果是月日格式且月份小于当前月，可能跨年
                if not re.search(r'20\d{2}', text) and dt < now:
                    dt = dt.replace(year=dt.year + 1)
                if 2024 <= dt.year <= 2028 and now <= dt <= CUTOFF:
                    return dt
            except: continue
    return None

def extract_band(title):
    """提取乐队名"""
    # 去掉日期前缀
    t = re.sub(r'^[\d.月日\/|：: ]+(?:丨|\|)?\s*', '', title)
    
    patterns = [
        r'([一-鿿A-Za-z·•]{2,16})(?:2026|巡演|专场|演唱会|全国巡演|广州站|深圳站|东莞站|佛山站|珠海站|中山站|[\d.]+(?:巡|专|演))',
        r'「([^」]{2,16})」',
        r'《([^》]{2,16})》',
        r'([一-鿿A-Za-z·•]{2,15})(?:乐队|乐团)',
        r'(?:乐队|乐团)([一-鿿A-Za-z·•]{2,15})',
    ]
    for p in patterns:
        m = re.search(p, t)
        if m:
            name = m.group(1).strip()
            if 2 <= len(name) <= 20:
                return name
    return t[:12]

# ====== 搜狗微信搜索 ======
def search_wechat():
    """搜微信搜演出"""
    shows = []
    seen = set()
    cities = ['广州', '深圳', '东莞', '佛山', '珠海', '中山']
    
    for city in cities:
        for kw in ['摇滚 演出', '乐队 巡演', '现场 演出']:
            q = f'{city} {kw}'
            url = f'https://weixin.sogou.com/weixin?type=2&query={urllib.parse.quote(q)}'
            html = fetch(url)
            if not html: continue
            
            items = re.findall(r'<div class="txt-box">(.*?)</div>', html, re.DOTALL)
            
            for item in items:
                title_m = re.search(r'<a[^>]*>(.*?)</a>', item, re.DOTALL)
                title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ''
                title = re.sub(r'&mdash;|&bull;|&ldquo;|&rdquo;', '', title)
                title = re.sub(r'\s+', ' ', title).strip()
                if not title: continue
                
                # 过滤演出相关
                if not any(k in title for k in ['演出','摇滚','现场','乐队','演唱会','音乐节','专场','巡演']):
                    continue
                
                # 找到对应的城市（检查标题是否包含目标城市）
                if city not in title and not any(c in title for c in cities):
                    continue
                
                # 提取日期
                dt = parse_date(title)
                
                # 只保留未来6个月
                if dt is None:
                    # 没写明日期就跳过（不确定是否在6个月内）
                    continue
                
                # 去重
                key = title[:30]
                if key in seen: continue
                seen.add(key)
                
                band = extract_band(title)
                
                shows.append({
                    'source': '微信公众号',
                    'city': city,
                    'name': title[:100],
                    'band': band,
                    'date': dt.strftime('%Y-%m-%d'),
                    'url': url,
                })
    
    return shows

# ====== 发邮件 ======
def send_email(shows):
    today = now.strftime('%Y年%m月%d日')
    now_str = now.strftime('%Y-%m-%d %H:%M')
    
    by_city = {}
    for s in shows:
        by_city.setdefault(s.get('city', '其他'), []).append(s)
    
    # 按日期排序
    shows.sort(key=lambda x: x.get('date', ''))
    
    html_items = ''
    if shows:
        for s in shows:
            html_items += f'''
            <div style="background:#1a1a2e;border-radius:12px;padding:16px;margin:14px 0;border:1px solid #30363d">
                <div style="display:flex;justify-content:space-between;align-items:start">
                    <div style="font-size:12px;color:#8b949e">{s.get('source','?')}</div>
                    <div style="font-size:14px;font-weight:700;color:#58a6ff">{s.get('date','?')}</div>
                </div>
                <div style="font-size:18px;font-weight:700;color:#e94560;margin-top:6px">{s.get('name','?')}</div>
                <div style="font-size:15px;color:#f0c040;margin-top:4px">🎤 {s.get('band','?')}</div>
                <div style="font-size:13px;color:#aaa;margin-top:4px">📍 {s.get('city','?')}</div>
            </div>'''
        
        html_body = f'''
        <div style="max-width:560px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0d1117;padding:24px;color:#e6edf3">
            <div style="text-align:center;padding:20px 0">
                <div style="font-size:40px;margin-bottom:8px">🎸</div>
                <h1 style="font-size:22px;font-weight:700;margin:0">广东摇滚演出日报</h1>
                <p style="color:#8b949e;font-size:13px">{today} · 未来6个月</p>
            </div>
            <div style="background:#1c2128;border-radius:12px;padding:20px;text-align:center;margin:16px 0">
                <div style="font-size:36px;font-weight:800;color:#e94560">{len(shows)}</div>
                <div style="color:#8b949e;font-size:13px">场演出 · {len(by_city)}个城市</div>
            </div>
            {html_items}
            <div style="text-align:center;padding:20px;color:#484f58;font-size:12px;margin-top:20px;border-top:1px solid #21262d">
                <p>数据来源：搜狗微信搜索</p>
                <p>⏱ {now_str}</p>
            </div>
        </div>'''
    else:
        html_body = f'''
        <div style="max-width:560px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0d1117;padding:24px;color:#e6edf3">
            <div style="text-align:center;padding:30px 0">
                <div style="font-size:40px;margin-bottom:8px">😴</div>
                <h1 style="font-size:22px;font-weight:700;margin:0">暂无演出</h1>
                <p style="color:#8b949e;font-size:13px">{today}</p>
            </div>
            <div style="background:#1c2128;border-radius:12px;padding:20px;text-align:center">
                <p style="color:#8b949e;font-size:14px">未来6个月广东省暂无摇滚演出信息</p>
                <p style="color:#484f58;font-size:12px;margin-top:8px">明日继续搜索</p>
            </div>
        </div>'''
    
    msg = MIMEText(html_body, 'html', 'utf-8')
    msg['Subject'] = Header(f'🎸 广东摇滚演出日报 {today}', 'utf-8')
    msg['From'] = '941189835@qq.com'
    msg['To'] = '941189835@qq.com'
    
    with smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=30) as s:
        s.login('941189835@qq.com', 'ualqcpqiekupbdej')
        s.sendmail('941189835@qq.com', ['941189835@qq.com'], msg.as_string())

# ====== 主入口 ======
def main():
    print(f'🔍 搜索广东摇滚演出 (未来6个月: {now.strftime("%Y-%m-%d")} ~ {CUTOFF.strftime("%Y-%m-%d")})')
    print(f'{", ".join(["广州","深圳","东莞","佛山","珠海","中山"])}\n')
    
    print('📡 搜狗微信搜索... ', end='', flush=True)
    shows = search_wechat()
    print(f'{len(shows)} 场\n')
    
    print(f'{"="*50}')
    print(f'未来6个月共 {len(shows)} 场演出')
    print(f'{"="*50}')
    
    for s in shows:
        print(f'\n  🎸 {s["name"]}')
        print(f'     🎤 {s["band"]} | 📍 {s["city"]} | 📅 {s["date"]}')
    
    print(f'\n📧 发送邮件... ', end='', flush=True)
    send_email(shows)
    print('✅ 成功')
    
    output = {
        'date': now.strftime('%Y-%m-%d %H:%M'),
        'count': len(shows),
        'shows': shows,
        'monitor_range': {
            'start': now.strftime('%Y-%m-%d'),
            'end': CUTOFF.strftime('%Y-%m-%d')
        }
    }
    print(f'\n---JSON---')
    print(json.dumps(output, ensure_ascii=False))

if __name__ == '__main__':
    main()
