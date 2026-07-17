@echo off
chcp 65001 >nul
title QQQ 加仓建议 - 手机端

echo.
echo ┌─────────────────────────────────────────────┐
echo │  QQQ 今日加仓建议 - 手机端                    │
echo │                                              │
echo │  确保手机连了和电脑同一个 WiFi 即可            │
echo │  关闭本窗口 = 停止服务                        │
echo └─────────────────────────────────────────────┘
echo.

cd /d "%~dp0"

:: 获取局域网 IP
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do set "IP=%%a"
set IP=%IP: =%

:: 启动文件服务器
start /B python -m http.server 5050 >nul 2>&1

echo  ✅ 服务器已启动
echo.
echo  📱 手机 Safari 打开：
echo     http://%IP%:5050
echo.
echo  💻 电脑本机打开：
echo     http://127.0.0.1:5050
echo.
echo  ⚠️ 手机和电脑必须连同一个 WiFi
echo     本窗口关闭后服务即停止
echo.
pause
