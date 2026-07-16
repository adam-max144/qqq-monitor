@echo off
chcp 65001 > nul
echo Creating scheduled task "QQQ Fetch VXN Data"...

schtasks /Create ^
  /SC MINUTE ^
  /MO 30 ^
  /TN "QQQ Fetch VXN Data" ^
  /TR "python.exe C:\Users\huawei\Desktop\qqq_web\fetch_vxn.py" ^
  /ST 09:00 ^
  /ET 23:59 ^
  /D MON,TUE,WED,THU,FRI ^
  /F

if %errorlevel% equ 0 (
  echo.
  echo [SUCCESS] Task created! Runs every 30 minutes, Mon-Fri 9:00-23:59.
  echo.
  echo Next step - test the script:
  echo   cd C:\Users\huawei\Desktop\qqq_web
  echo   python fetch_vxn.py
) else (
  echo [ERROR] Failed to create task. Run this script as Administrator.
)

pause