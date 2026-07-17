#!/usr/bin/env python3
"""一键部署到 Netlify — 无需注册、无需网页、无需拖拽"""
import urllib.request, json, os, zipfile, io, time, socket

def deploy():
    filepath = os.path.join(os.path.dirname(__file__), 'static_index.html')
    if not os.path.exists(filepath):
        print(f'❌ 找不到 {filepath}')
        return
    
    # 读取文件
    with open(filepath, 'rb') as f:
        content = f.read()
    
    print('📤 正在上传到 Netlify...')
    
    # 创建 zip（Netlify 接受 zip 格式的部署）
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('index.html', content)
    buf.seek(0)
    
    # 使用 Netlify 的自动部署 API（不需要 token，第一次部署自动创建站点）
    # 尝试直接上传 zip
    req = urllib.request.Request(
        'https://api.netlify.com/api/v1/sites',
        data=buf.getvalue(),
        headers={
            'Content-Type': 'application/zip',
            'User-Agent': 'QQQ-Deploy/1.0',
        },
        method='POST'
    )
    
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        site_url = result.get('ssl_url') or result.get('url', '')
        site_name = result.get('name', '')
        admin_url = f'https://app.netlify.com/sites/{site_name}'
        
        print(f'\n✅ 部署成功！')
        print(f'{"="*50}')
        print(f'📱 手机打开（WiFi/流量均可）:')
        print(f'   {site_url}')
        print(f'')
        print(f'🔧 管理后台（可绑定自定义域名）:')
        print(f'   {admin_url}')
        print(f'{"="*50}')
        print(f'\n⚠️  24小时内无人认领会自动删除')
        print(f'   建议在管理后台注册账号认领以永久保留')
        
    except urllib.error.HTTPError as e:
        print(f'❌ HTTP 错误: {e.code} {e.reason}')
        print(f'   响应: {e.read().decode()[:200]}')
    except urllib.error.URLError as e:
        print(f'❌ 网络错误: {e.reason}')
        print(f'   可能是国内无法直连 Netlify API')
        print(f'   请尝试方案 B：手动拖拽')
        print(f'   访问 https://app.netlify.com/drop')
        print(f'   拖入 static_index.html 即可')

if __name__ == '__main__':
    deploy()
    input('\n按回车退出...')
