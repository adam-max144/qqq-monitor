@echo off
chcp 65001 >nul

echo ┌──────────────────────────────────────┐
echo │  QQQ加仓建议 — 一键启动              │
echo │  手机浏览器打开下方网址即可查看        │
echo │  关闭本窗口 = 停止服务                │
echo └──────────────────────────────────────┘
echo.

:: 进入目录
cd /d "%~dp0"

:: 启动HTTP服务器（后台）
start /B python -m http.server 5050 --bind 0.0.0.0

:: 等一秒
timeout /t 1 /nobreak >nul

:: 建立公开隧道
echo 正在建立公开访问链接...
echo.
ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -R 80:localhost:5050 nokey@localhost.run 2>&1 | findstr "https://"
echo.
echo 如果上面没有显示网址，等10秒后按 Ctrl+C 重试
echo 手机打开显示的网址即可查看（支持WiFi和流量）
echo.

:: 保持窗口打开
pause
