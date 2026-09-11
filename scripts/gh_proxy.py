# -*- coding: utf-8 -*-
"""GitHub 连接临时代理: 把 github.com 转发到可用 IP(绕过本地DNS把github.com指向不可达的亚洲边缘节点)
用法: python gh_proxy.py & 然后 git -c http.proxy=http://127.0.0.1:7890 push
启动即监听; 首个请求时自动探测候选 IP 的 TLS 握手耗时取最快(GH_PROXY_IP 可手工指定, 免探测)。
push 建议加: -c http.version=HTTP/1.1 -c http.postBuffer=52428800 -c http.lowSpeedLimit=0
"""
import os, socket, ssl, threading, sys, time
sys.stdout.reconfigure(encoding='utf-8')
LISTEN = ('127.0.0.1', 7890)
CANDIDATES = ['20.27.177.113', '140.82.113.3', '140.82.114.3', '140.82.113.4', '20.27.177.114', '20.205.243.168']
# 2026-09-11 实测: 这些 IP 会"按连接"间歇性掐断(探测刚通过, 下一个 connect 就超时) → 候选要多 + 运行时逐个回退

def probe(ip, tries=2, timeout=6):
    """TLS 握手计时; 这些 IP 会被间歇性干扰, 故单 IP 重试 tries 次, 全失败才判不可用。返回 (秒, 最后错误)"""
    err = None
    for _ in range(tries):
        t0 = time.time()
        try:
            c = ssl.create_default_context().wrap_socket(
                socket.create_connection((ip, 443), timeout=timeout), server_hostname='github.com')
            c.close()
            return time.time() - t0, None
        except Exception as e:
            err = f'{type(e).__name__}: {e}'
    return None, err

def pick_ips():
    """惰性探测, 返回按握手耗时排序的可用 IP 列表(GH_PROXY_IP 指定时只用它)。
    为什么是列表: 这些 IP 会被"按连接"间歇性干扰 — 探测通 ≠ 下一个连接通, 故运行时逐个回退。"""
    env = os.environ.get('GH_PROXY_IP')
    if env:
        print('GH_PROXY_IP 指定:', env)
        return [env]
    got = []
    for ip in CANDIDATES:
        dt, err = probe(ip)
        print(f'  探测 {ip}: ' + (f'{dt:.2f}s' if dt else f'FAIL ({err})'))
        if dt:
            got.append((dt, ip))
            if len(got) >= 3:                   # 有 3 个可用就够回退了, 不再陪跑剩下的候选
                break
    if not got:
        sys.exit('候选 IP 全部不可用 — 请设 GH_PROXY_IP 或等待网络恢复')
    got.sort()
    print('回退顺序:', ' > '.join(ip for _, ip in got))
    return [ip for _, ip in got]

_ips_lock = threading.Lock()
_ips = None

def ips():
    global _ips
    if _ips is None:
        with _ips_lock:
            if _ips is None:
                _ips = pick_ips()
    return _ips

def pipe(a, b):
    try:
        while True:
            d = a.recv(65536)
            if not d: break
            b.sendall(d)
    except Exception:
        pass
    finally:
        for s in (a, b):
            try: s.close()
            except Exception: pass

def handle(c):
    stage = 'read-req'
    try:
        c.settimeout(10)
        req = b''
        while b'\r\n\r\n' not in req:
            chunk = c.recv(4096)
            if not chunk: return
            req += chunk
        stage = 'parse'
        line = req.split(b'\r\n', 1)[0].decode('ascii', 'replace')
        parts = line.split()
        if parts[0].upper() != 'CONNECT' or len(parts) < 2:
            c.sendall(b'HTTP/1.1 405 Method Not Allowed\r\n\r\n'); return
        host, _, port = parts[1].partition(':')
        host, port = host.lower(), int(port.partition(':')[0] or 443)
        stage = 'resolve-ip'
        ip_list = ips() if host == 'github.com' else [host]
        stage = 'connect-upstream'
        up, last = None, None
        for attempt in range(2):                # 单轮常被间歇封锁全灭 → 隔 2 秒再来一轮
            for ip in ip_list:
                try:
                    up = socket.create_connection((ip, port), timeout=8)
                    break
                except Exception as e:
                    last = e
                    print(f'  上游 {ip} 失败: {type(e).__name__}: {e}')
            if up:
                break
            time.sleep(2)
        if up is None:
            c.sendall(b'HTTP/1.1 502 Bad Gateway\r\n\r\n')
            raise last
        stage = 'establish'
        c.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
        c.settimeout(None); up.settimeout(None)
        t1 = threading.Thread(target=pipe, args=(c, up), daemon=True)
        t2 = threading.Thread(target=pipe, args=(up, c), daemon=True)
        t1.start(); t2.start(); t1.join(); t2.join()
    except Exception as e:
        print(f'ERR[{stage}]', type(e).__name__, repr(e)[:100])
        try: c.close()
        except Exception: pass

s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(LISTEN); s.listen(8)
print('gh_proxy listening', LISTEN)
while True:
    c, _ = s.accept()
    threading.Thread(target=handle, args=(c,), daemon=True).start()
