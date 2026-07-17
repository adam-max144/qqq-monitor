#!/usr/bin/env python3
"""GitHub部署脚本 - 通过环境变量传递token"""
import os, urllib.request, json, subprocess

token = os.environ.get('GH_TOKEN', '')
user  = 'adam-max144'
if not token:
    print('❌ 需要设置 GH_TOKEN 环境变量')
    exit(1)

# 1. 创建仓库
req = urllib.request.Request(
    "https://api.github.com/user/repos",
    data=json.dumps({"name":"qqq-monitor","private":False,"description":"QQQ今日加仓建议"}).encode(),
    headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    },
    method="POST"
)
try:
    resp = urllib.request.urlopen(req, timeout=15)
    d = json.loads(resp.read())
    print(f"✅ 仓库已创建: {d['html_url']}")
except urllib.error.HTTPError as e:
    err = json.loads(e.read())
    msg = err.get('message','')
    print(f"创建结果: {msg}")
    if e.code != 422:
        exit(1)

# 2. 推送代码
os.chdir(os.path.dirname(__file__))
r = subprocess.run([
    'git','remote','add','origin',
    f'https://adam-max144:{token}@github.com/{user}/qqq-monitor.git'
], capture_output=True, text=True)
if r.returncode != 0 and 'already exists' not in r.stderr:
    # 已存在则更新remote
    subprocess.run(['git','remote','set-url','origin',
        f'https://adam-max144:{token}@github.com/{user}/qqq-monitor.git'])

r = subprocess.run(['git','push','-u','origin','main'], capture_output=True, text=True, timeout=30)
print(r.stdout[-200:] if r.stdout else '')
if r.returncode != 0:
    print(f'推送: {r.stderr[-200:]}')
    exit(1)
print('✅ 代码已推送')

# 3. 启用GitHub Pages
req2 = urllib.request.Request(
    f"https://api.github.com/repos/{user}/qqq-monitor/pages",
    data=json.dumps({"source":{"branch":"main","path":"/"}}).encode(),
    headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    },
    method="POST"
)
try:
    resp2 = urllib.request.urlopen(req2, timeout=15)
    d2 = json.loads(resp2.read())
    print(f"✅ GitHub Pages 已启用")
except urllib.error.HTTPError as e:
    err = json.loads(e.read())
    print(f"Pages: {err.get('message','')}")
    # 可能已启用，尝试获取
    try:
        req3 = urllib.request.Request(
            f"https://api.github.com/repos/{user}/qqq-monitor/pages",
            headers={"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        )
        resp3 = urllib.request.urlopen(req3, timeout=15)
        d3 = json.loads(resp3.read())
        print(f"Pages 状态: {d3.get('html_url','')}")
    except:
        pass

print(f'\n📱 最终网址:')
print(f'   https://{user}.github.io/qqq-monitor/')
print(f'   手机随时随地可打开（WiFi/流量）')
