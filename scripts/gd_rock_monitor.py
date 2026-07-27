#!/usr/bin/env python3
"""
广东省摇滚演出监控 — GitHub Actions 版
多数据源：秀动网API搜索 + 大麦网 + 搜索引擎兜底
每天早上8点自动检查，发现新演出发邮件通知
"""
import json, urllib.request, urllib.parse, re, ssl, smtplib
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime, timezone, timedelta

# ====== 配置区 ======
CITIES = ['广州', '深圳', '东莞', '佛山', '珠海', '中山', '惠州', '汕头']
KEYWORDS = ['摇滚', '金属', '朋克', '独立音乐', '现场演出', '乐队', '演唱会', '音乐节']
# ===================

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}
TIMEOUT = 20

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
    except Exception as e:
        return None

def safe_json(text):
    try: return json.loads(text)
    except: return None

# ====== 秀动网搜索 ======
def search_showstart():
    """秀动网POST API"""
    shows = []
    api = 'https://www.showstart.com/api/event/list'
    headers = {**HEADERS, 'Content-Type': 'application/json',
               'Origin': 'https://www.showstart.com',
               'Referer': 'https://www.showstart.com/event/list'}
    
    # 秀动城市代码
    city_codes = {'广州':57, '深圳':56, '东莞':97, '佛山':150, 
                  '珠海':96, '中山':98, '惠州':99, '汕头':93}
    
    for city_name, code in city_codes.items():
        try:
            payload = json.dumps({"cityCode":code,"pageNo":1,"pageSize":20}).encode()
            req = urllib.request.Request(api, data=payload, headers=headers, method='POST')
            resp = urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx)
            data = json.loads(resp.read().decode())
            
            if data.get('success') and data.get('data'):
                for ev in data['data'].get('list', []):
                    name = (ev.get('eventName') or '').strip()
                    style = (ev.get('styleName') or '') + (ev.get('eventTypeName') or '')
                    if not name: continue
                    
                    tag = (name + style).lower()
                    if any(kw in tag for kw in ['摇滚','滚','rock','金属','metal','punk',
                                                   '朋克','乐队','band','live','独立','indie',
                                                   '后摇','核','core','重型','hardcore',
                                                   '硬核','英伦','britpop','民谣']):
                        shows.append({
                            'source': '秀动网', 'city': city_name,
                            'name': name, 'date': ev.get('eventDate',''),
                            'venue': ev.get('venueName',''),
                            'style': ev.get('styleName',''),
                            'price': ev.get('priceDesc',''),
                            'url': ev.get('shareUrl','') or f'https://www.showstart.com/event/{ev.get("eventId","")}',
                        })
        except:
            pass
    return shows

# ====== 大麦网搜索 ======
def search_damai():
    """大麦网搜索页抓取"""
    shows = []
    for city in CITIES:
        for kw in ['摇滚', '乐队', '演唱会']:
            url = f'https://search.damai.cn/search.htm?keyword={urllib.parse.quote(kw)}&cty={urllib.parse.quote(city)}'
            html = fetch(url)
            if not html: continue
            
            # 尝试提取演出标题
            titles = re.findall(r'title="([^"]{4,80})"', html)
            for t in titles:
                if any(k in t for k in ['摇滚','乐队','live','演唱会','音乐节','现场']):
                    if city in html or True:
                        shows.append({
                            'source': '大麦网', 'city': city,
                            'name': t.strip(),
                            'url': f'https://search.damai.cn/search.htm?keyword={urllib.parse.quote(t.strip()[:20])}',
                        })
    return shows

# ====== 搜索引擎搜索 ======
def search_web():
    """通过搜索引擎搜索演出信息"""
    shows = []
    search_urls = []
    
    for city in CITIES:
        for kw in KEYWORDS[:2]:  # 只搜"摇滚"和"金属"
            # 百度搜索
            q = f'{city} {kw} 演出 2026'
            search_urls.append(
                f'https://www.baidu.com/s?wd={urllib.parse.quote(q)}&tn=SE_baiduhome_pg'
            )
            # 必应搜索
            search_urls.append(
                f'https://www.bing.com/search?q={urllib.parse.quote(q)}&setlang=zh-cn'
            )
    
    seen = set()
    for url in search_urls:
        html = fetch(url, {**HEADERS, 'Accept-Language': 'zh-CN,zh;q=0.9'})
        if not html: continue
        
        # 从搜索结果中提取演出信息
        # 日期+城市+演出名称 模式
        patterns = [
            r'(?:20\d{2})[-./年]\d{1,2}[-./月]\d{1,2}[^\s。<"]{0,30}(?:广州|深圳|佛山|东莞|珠海|中山)[^\s。<"]{0,30}(?:摇滚|音乐|乐队|演唱|金属|live|Live)',
            r'(?:广州|深圳|佛山|东莞|珠海|中山)[^\s。<"]{0,20}(?:摇滚|音乐|乐队|演唱|金属|音乐节|live|Live)[^\s。<"]{0,30}(?:20\d{2})[-./年]\d{1,2}[-./月]\d{1,2}',
            r'(?:摇滚|乐队|演唱|音乐节|金属)[^\s。<"]{0,20}(?:20\d{2})[-./年]\d{1,2}[-./月]\d{1,2}[^\s。<"]{0,20}(?:广州|深圳|佛山|东莞|珠海|中山)',
        ]
        
        for p in patterns:
            matches = re.findall(p, html)
            for m in matches:
                m_clean = re.sub(r'<[^>]+>', '', m).strip()
                if m_clean and m_clean not in seen:
                    seen.add(m_clean)
                    shows.append({
                        'source': '搜索引擎',
                        'name': m_clean[:80],
                        'url': url,
                    })
    return shows

# ====== 邮件发送 ======
def send_email(shows):
    """发送QQ邮件"""
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).strftime('%Y-%m-%d %H:%M')
    
    today = datetime.now(tz).strftime('%Y年%m月%d日')
    
    # 创建HTML邮件
    if shows:
        html_items = ''
        for s in shows:
            src = s.get('source', '?')
            html_items += f'''
            <div style="background:#1a1a2e;border-radius:12px;padding:16px;margin:12px 0;border:1px solid #333;color:#e0e0e0">
                <div style="font-size:13px;color:#888;margin-bottom:4px">🎸 {src}</div>
                <div style="font-size:17px;font-weight:700;color:#e94560">{s.get('name','?')}</div>
                <div style="font-size:13px;color:#aaa;margin-top:6px">
                    📍 {s.get('city','?')} | 📅 {s.get('date','?')}
                </div>
                {f'<div style="font-size:13px;color:#aaa">🏟 {s["venue"]}</div>' if s.get('venue') else ''}
                {f'<div style="font-size:13px;color:#aaa">💰 {s["price"]}</div>' if s.get('price') else ''}
                {f'<a href="{s["url"]}" style="display:inline-block;margin-top:10px;padding:6px 16px;background:#e94560;color:#fff;border-radius:6px;text-decoration:none;font-size:13px">查看详情 →</a>' if s.get('url') else ''}
            </div>'''
        
        html_body = f'''
        <div style="max-width:560px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0d1117;padding:24px;color:#e6edf3">
            <div style="text-align:center;padding:20px 0">
                <div style="font-size:40px;margin-bottom:8px">🎸</div>
                <h1 style="font-size:22px;font-weight:700;margin:0">广东省摇滚演出日报</h1>
                <p style="color:#8b949e;font-size:13px;margin:4px 0 0">{today}</p>
            </div>
            <div style="background:#1c2128;border-radius:12px;padding:20px;text-align:center;margin:16px 0">
                <div style="font-size:36px;font-weight:800;color:#e94560">{len(shows)}</div>
                <div style="color:#8b949e;font-size:13px">场演出今日发现</div>
            </div>
            {html_items}
            <div style="text-align:center;padding:20px;color:#484f58;font-size:12px;margin-top:20px;border-top:1px solid #21262d">
                <p>数据来源：秀动网 / 大麦网 / 搜索引擎</p>
                <p>每日自动监控 · 发现新演出即推送</p>
                <p style="margin-top:4px">🔄 下次检查：{now}</p>
            </div>
        </div>'''
    else:
        html_body = f'''
        <div style="max-width:560px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0d1117;padding:24px;color:#e6edf3">
            <div style="text-align:center;padding:30px 0">
                <div style="font-size:40px;margin-bottom:8px">😴</div>
                <h1 style="font-size:22px;font-weight:700;margin:0">暂无新演出</h1>
                <p style="color:#8b949e;font-size:13px;margin:4px 0 0">{today}</p>
            </div>
            <div style="background:#1c2128;border-radius:12px;padding:20px;text-align:center">
                <p style="color:#8b949e;font-size:14px">今天在广东省没有发现新的摇滚演出</p>
                <p style="color:#484f58;font-size:12px;margin-top:8px">明日将继续监控</p>
            </div>
            <div style="text-align:center;padding:20px;color:#484f58;font-size:12px;margin-top:20px">
                <p>🔄 下次检查：{now}</p>
            </div>
        </div>'''
    
    msg = MIMEText(html_body, 'html', 'utf-8')
    msg['Subject'] = Header(f'🎸 广东摇滚演出日报 {today}', 'utf-8')
    
    # QQ邮箱SMTP
    smtp_host = 'smtp.qq.com'
    smtp_port = 465
    sender = '941189835@qq.com'
    password = 'ualqcpqiekupbdej'
    receivers = ['941189835@qq.com']
    
    msg['From'] = sender
    msg['To'] = ','.join(receivers)
    
    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as s:
            s.login(sender, password)
            s.sendmail(sender, receivers, msg.as_string())
        return True
    except Exception as e:
        print(f'邮件发送失败: {e}')
        return False

# ====== 主入口 ======
def main():
    print(f'🔍 搜索广东省摇滚演出...')
    print(f'目标城市: {", ".join(CITIES)}')
    
    all_shows = []
    
    # 秀动网
    print(f'\n📡 秀动网... ', end='', flush=True)
    try:
        shows = search_showstart()
        print(f'{len(shows)} 场')
        all_shows.extend(shows)
    except Exception as e:
        print(f'失败: {e}')
    
    # 大麦网
    print(f'📡 大麦网... ', end='', flush=True)
    try:
        shows = search_damai()
        print(f'{len(shows)} 场')
        all_shows.extend(shows)
    except Exception as e:
        print(f'失败: {e}')
    
    # 搜索引擎
    print(f'📡 搜索引擎... ', end='', flush=True)
    try:
        shows = search_web()
        print(f'{len(shows)} 条')
        all_shows.extend(shows)
    except Exception as e:
        print(f'失败: {e}')
    
    # 去重
    seen_names = set()
    unique_shows = []
    for s in all_shows:
        key = s.get('name', '')[:30]
        if key not in seen_names:
            seen_names.add(key)
            unique_shows.append(s)
    
    print(f'\n{"="*50}')
    print(f'共找到 {len(unique_shows)} 场演出（去重后）')
    print(f'{"="*50}')
    
    for s in unique_shows:
        print(f'\n  🎸 [{s["source"]}] {s.get("name","?")}')
        print(f'     📍 {s.get("city","?")} | 📅 {s.get("date","?")}')
        if s.get('venue'): print(f'     🏟 {s["venue"]}')
        if s.get('price'): print(f'     💰 {s["price"]}')
    
    # 发送邮件
    print(f'\n📧 发送邮件... ', end='', flush=True)
    if send_email(unique_shows):
        print('✅ 成功')
    else:
        print('❌ 失败')
    
    # 输出JSON供GitHub Actions后续使用
    output = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'count': len(unique_shows),
        'shows': unique_shows,
    }
    print(f'\n---JSON_OUTPUT---')
    print(json.dumps(output, ensure_ascii=False))

if __name__ == '__main__':
    main()
