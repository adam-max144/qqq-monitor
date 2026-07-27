#!/usr/bin/env python3
"""
广东省摇滚演出监控 — GitHub Actions 版
多数据源：秀动网API搜索 + 大麦网 + 搜索引擎兜底
每天早上8点自动检查 → 只显示未来6个月内的演出 → QQ邮件推送
"""
import json, urllib.request, urllib.parse, re, ssl, smtplib
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime, timezone, timedelta

# ====== 配置 ======
CITIES = ['广州', '深圳', '东莞', '佛山', '珠海', '中山', '惠州', '汕头']
KEYWORDS = ['摇滚', '金属', '朋克', '独立音乐', '现场演出', '乐队', '演唱会', '音乐节']
# ==================

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}
TIMEOUT = 20

now = datetime.now(timezone(timedelta(hours=8)))
CUTOFF = now + timedelta(days=180)  # 未来6个月

def fetch(url, headers=None):
    if headers is None: headers = HEADERS
    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx)
        raw = resp.read()
        for enc in ('utf-8', 'gbk', 'gb2312'):
            try: return raw.decode(enc)
            except: continue
        return raw.decode('utf-8', errors='replace')
    except: return None

# ====== 日期工具 ======
DATE_PATTERNS = [
    r'(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})',           # 2026-07-27 / 2026年07月27日
    r'(\d{1,2})月(\d{1,2})日',                                 # 7月27日
    r'(20\d{2})[-./年](\d{1,2})',                              # 2026-07
    r'(\d{1,2})月',                                             # 7月（无年份）
]

def parse_date(text):
    """从文本中提取日期, 返回datetime或None"""
    if not text: return None
    for p in DATE_PATTERNS:
        m = re.search(p, text)
        if m:
            try:
                groups = m.groups()
                if len(groups) == 3:
                    y, mo, d = int(groups[0]), int(groups[1]), int(groups[2])
                elif len(groups) == 2 and len(groups[0]) == 4:
                    y, mo, d = int(groups[0]), int(groups[1]), 1
                elif len(groups) == 2:
                    mo, d = int(groups[0]), int(groups[1])
                    y = now.year
                    # 如果月份小于当前月,可能跨年了
                    if mo < now.month: y += 1
                elif len(groups) == 1:
                    mo = int(groups[0])
                    y = now.year if mo >= now.month else now.year + 1
                    d = 15  # 月中估算
                else:
                    continue
                
                if y < 2024 or y > 2028: continue
                if mo < 1 or mo > 12: continue
                if d < 1 or d > 31: continue
                
                return datetime(y, mo, d, tzinfo=timezone(timedelta(hours=8)))
            except:
                continue
    return None

def in_future_6m(text):
    """检查日期是否在未来6个月内"""
    dt = parse_date(text)
    if dt is None: return False  # 无法解析日期就不显示
    return now <= dt <= CUTOFF

# ====== 提取乐队名 ======
def extract_band(name, extra_text=''):
    """从演出名称中提取乐队/艺人名"""
    full = f"{name} {extra_text}"
    
    # 常见模式：XXX专场 / XXX演唱会 / XXX巡演
    patterns = [
        r'([\u4e00-\u9fff\w·•.-]+?)(?:专场|演唱会|巡演|音乐会|2026|全国|中国|之旅|巡回)',
        r'「([^」]+)」.*?([\u4e00-\u9fff\w·•.-]+?)(?:专场|巡演|演唱会)',
        r'([\u4e00-\u9fff\w·•.-]+?)(?:×|X|x|\+)([\u4e00-\u9fff\w·•.-]+?)',
        r'《([^》]+)》',
    ]
    
    for p in patterns:
        m = re.search(p, full)
        if m:
            band = m.group(1).strip()
            if len(band) >= 2 and len(band) <= 30:
                return band
    
    # 兜底：取前2~15个字
    name_clean = re.sub(r'(?:2026|2025|音乐会|演唱会|专场|巡演|全国|广州|深圳|东莞|佛山|珠海|中山).*', '', name)
    name_clean = name_clean.strip().strip('《》「」')
    if 2 <= len(name_clean) <= 20:
        return name_clean
    
    return name[:20]

# ====== 秀动网 ======
def search_showstart():
    """秀动网搜索"""
    shows = []
    api = 'https://www.showstart.com/api/event/list'
    headers = {**HEADERS, 'Content-Type': 'application/json',
               'Origin': 'https://www.showstart.com',
               'Referer': 'https://www.showstart.com/event/list'}
    
    # 秀动城市代码(数值型)
    city_codes = {'广州':57, '深圳':56, '东莞':97, '佛山':150,
                  '珠海':96, '中山':98, '惠州':99, '汕头':93}
    
    ROCK_KEYWORDS = ['摇滚','滚','rock','金属','metal','punk','朋克','乐队','band',
                     'live','独立','indie','后摇','核','core','重型','hardcore',
                     '硬核','英伦','britpop','民谣','流行','pop','电子','elect']
    
    for city_name, code in city_codes.items():
        try:
            payload = json.dumps({"cityCode":code,"pageNo":1,"pageSize":50}).encode()
            req = urllib.request.Request(api, data=payload, headers=headers, method='POST')
            resp = urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx)
            data = json.loads(resp.read().decode())
            
            if data.get('success') and data.get('data'):
                for ev in data['data'].get('list', []):
                    name = (ev.get('eventName') or '').strip()
                    style = (ev.get('styleName') or '') + (ev.get('eventTypeName') or '')
                    event_date = ev.get('eventDate', '')
                    if not name: continue
                    
                    tag = (name + style).lower()
                    if not any(kw in tag for kw in ROCK_KEYWORDS): continue
                    # 时间过滤
                    combined_date = f"{event_date} {name}"
                    if not in_future_6m(combined_date): continue
                    
                    band = extract_band(name, style)
                    shows.append({
                        'source': '秀动网', 'city': city_name,
                        'name': name, 'band': band,
                        'date': event_date,
                        'venue': ev.get('venueName',''),
                        'style': ev.get('styleName',''),
                        'price': ev.get('priceDesc',''),
                        'url': ev.get('shareUrl','') or f'https://www.showstart.com/event/{ev.get("eventId","")}',
                    })
        except:
            pass
    return shows

# ====== 大麦网 ======
def search_damai():
    """大麦网搜索"""
    shows = []
    for city in CITIES:
        for kw in ['摇滚', '乐队', '演唱会']:
            url = f'https://search.damai.cn/search.htm?keyword={urllib.parse.quote(kw)}&cty={urllib.parse.quote(city)}'
            html = fetch(url)
            if not html: continue
            
            # 提取演出标题和可能的时间
            titles = re.findall(r'title="([^"]{4,80})"', html)
            dates_in_page = re.findall(r'(20\d{2}[-./年]\d{1,2}[-./月]\d{1,2})', html)
            
            for t in titles:
                if not any(k in t for k in ['摇滚','乐队','live','演唱会','音乐节','现场']):
                    continue
                
                # 找最近的日期
                closest_date = ''
                for d in dates_in_page:
                    if in_future_6m(d):
                        closest_date = d
                        break
                
                band = extract_band(t)
                shows.append({
                    'source': '大麦网', 'city': city,
                    'name': t.strip(), 'band': band,
                    'date': closest_date,
                    'url': f'https://search.damai.cn/search.htm?keyword={urllib.parse.quote(t.strip()[:20])}',
                })
    return shows

# ====== 搜索引擎 ======
def search_web():
    """搜索引擎抓取"""
    shows = []
    seen = set()
    
    for city in CITIES:
        for kw in KEYWORDS[:3]:
            for engine in ['baidu', 'bing']:
                if engine == 'baidu':
                    q = f'{city} {kw} 演出'
                    url = f'https://www.baidu.com/s?wd={urllib.parse.quote(q)}&tn=SE_baiduhome_pg'
                else:
                    q = f'{city} {kw} 演唱会 2026'
                    url = f'https://www.bing.com/search?q={urllib.parse.quote(q)}&setlang=zh-cn'
                
                html = fetch(url, {**HEADERS, 'Accept-Language': 'zh-CN,zh;q=0.9'})
                if not html: continue
                
                # 提取搜索结果片段
                snippets = re.findall(r'<div[^>]*class="[^"]*(?:result|c-abstract|b_algo)[^"]*"[^>]*>.*?</div>', html, re.DOTALL)
                if not snippets:
                    snippets = re.findall(r'<p[^>]*class="[^"]*"?[^>]*>(.*?)</p>', html, re.DOTALL)
                
                for sn in snippets:
                    text = re.sub(r'<[^>]+>', ' ', sn)
                    text = re.sub(r'\s+', ' ', text).strip()
                    
                    # 必须包含城市和关键词
                    if city not in text: continue
                    if not any(k in text.lower() for k in ['摇滚','乐队','演唱','音乐','金属','专场']):
                        continue
                    
                    # 提取日期
                    dates_found = re.findall(r'(20\d{2}[-./年]\d{1,2}[-./月]\d{1,2})', text)
                    
                    for d in dates_found:
                        if not in_future_6m(d): continue
                        
                        key = text[:50]
                        if key in seen: continue
                        seen.add(key)
                        
                        band = extract_band(text)
                        shows.append({
                            'source': f'搜索引擎({engine})',
                            'city': city,
                            'name': text[:80].replace(city, f'[{city}]'),
                            'band': band,
                            'date': d,
                            'url': url,
                        })
                        break  # 每个片段只取一个日期
    return shows

# ====== 发邮件 ======
def send_email(shows):
    today = now.strftime('%Y年%m月%d日')
    now_str = now.strftime('%Y-%m-%d %H:%M')
    
    # 按城市分组
    by_city = {}
    for s in shows:
        c = s.get('city', '其他')
        by_city.setdefault(c, []).append(s)
    
    html_items = ''
    if shows:
        for city in CITIES:
            if city not in by_city: continue
            city_shows = by_city[city]
            html_items += f'''
            <div style="margin-top:20px">
                <div style="font-size:15px;font-weight:700;color:#58a6ff;padding:8px 0;border-bottom:1px solid #21262d">
                    📍 {city} · {len(city_shows)}场
                </div>'''
            for s in city_shows:
                html_items += f'''
                <div style="background:#1a1a2e;border-radius:12px;padding:16px;margin:12px 0;border:1px solid #30363d">
                    <div style="display:flex;justify-content:space-between;align-items:start">
                        <div>
                            <div style="font-size:13px;color:#8b949e">{s.get('source','?')}</div>
                            <div style="font-size:18px;font-weight:700;color:#e94560;margin-top:2px">{s.get('name','?')}</div>
                            {f'<div style="font-size:14px;color:#f0c040;margin-top:2px">🎤 乐队：{s["band"]}</div>' if s.get('band') else ''}
                        </div>
                    </div>
                    <div style="font-size:13px;color:#aaa;margin-top:8px">
                        📅 {s.get('date','?')}{f' | 🏟 {s["venue"]}' if s.get('venue') else ''}{f' | 💰 {s["price"]}' if s.get('price') else ''}
                    </div>
                    {f'<a href="{s["url"]}" style="display:inline-block;margin-top:10px;padding:6px 16px;background:#238636;color:#fff;border-radius:6px;text-decoration:none;font-size:13px">查看详情 →</a>' if s.get('url') else ''}
                </div>'''
            html_items += '</div>'
        
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
                <p>数据：秀动网 / 大麦网 / 百度 / 必应</p>
                <p>⏱ 下次检查：{now_str}</p>
            </div>
        </div>'''
    else:
        html_body = f'''
        <div style="max-width:560px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0d1117;padding:24px;color:#e6edf3">
            <div style="text-align:center;padding:30px 0">
                <div style="font-size:40px;margin-bottom:8px">😴</div>
                <h1 style="font-size:22px;font-weight:700;margin:0">暂无新演出</h1>
                <p style="color:#8b949e;font-size:13px">{today}</p>
            </div>
            <div style="background:#1c2128;border-radius:12px;padding:20px;text-align:center">
                <p style="color:#8b949e;font-size:14px">未来6个月广东省暂无摇滚演出信息</p>
                <p style="color:#484f58;font-size:12px;margin-top:8px">明日继续监控</p>
            </div>
            <div style="text-align:center;padding:20px;color:#484f58;font-size:12px;margin-top:20px">
                <p>⏱ 下次检查：{now_str}</p>
            </div>
        </div>'''
    
    msg = MIMEText(html_body, 'html', 'utf-8')
    msg['Subject'] = Header(f'🎸 广东摇滚演出日报 {today}', 'utf-8')
    msg['From'] = '941189835@qq.com'
    msg['To'] = '941189835@qq.com'
    
    try:
        with smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=30) as s:
            s.login('941189835@qq.com', 'ualqcpqiekupbdej')
            s.sendmail('941189835@qq.com', ['941189835@qq.com'], msg.as_string())
        return True
    except Exception as e:
        print(f'邮件发送失败: {e}')
        return False


# ====== 主入口 ======
def main():
    print(f'🔍 搜索广东摇滚演出 (未来6个月: {now.strftime("%Y-%m-%d")} ~ {CUTOFF.strftime("%Y-%m-%d")})')
    print(f'目标城市: {", ".join(CITIES)}\n')
    
    all_shows = []
    
    for name, fn in [('秀动网', search_showstart), ('大麦网', search_damai), ('搜索引擎', search_web)]:
        print(f'📡 {name}... ', end='', flush=True)
        try:
            shows = fn()
            print(f'{len(shows)} 场')
            all_shows.extend(shows)
        except Exception as e:
            print(f'失败: {e}')
    
    # 去重+排序
    seen = set()
    unique = []
    for s in all_shows:
        key = f"{s.get('band','')}_{s.get('name','')[:30]}"
        if key not in seen:
            seen.add(key)
            unique.append(s)
    
    # 按城市排序
    city_order = {c: i for i, c in enumerate(CITIES)}
    unique.sort(key=lambda x: (city_order.get(x.get('city',''), 99), x.get('date','')))
    
    print(f'\n{"="*50}')
    print(f'未来6个月共 {len(unique)} 场演出')
    print(f'{"="*50}')
    
    for s in unique:
        print(f'\n  🎸 [{s["source"]}] {s.get("name","?")}')
        print(f'     🎤 乐队: {s.get("band","?")}')
        print(f'     📍 {s.get("city","?")} | 📅 {s.get("date","?")}')
        if s.get('venue'): print(f'     🏟 {s["venue"]}')
    
    print(f'\n📧 发送邮件... ', end='', flush=True)
    if send_email(unique):
        print('✅ 成功')
    else:
        print('❌ 失败')
    
    now_str = now.strftime('%Y-%m-%d %H:%M')
    output = {'date': now_str, 'count': len(unique), 'shows': unique}
    print(f'\n---JSON---')
    print(json.dumps(output, ensure_ascii=False))

if __name__ == '__main__':
    main()
