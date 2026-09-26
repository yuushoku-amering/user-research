@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Restart User Research Workbench

set "PYW=D:\GPT-SoVITS\GPT-SoVITS-v2pro-20250604\runtime\python.exe"

echo.
echo  重启用户研究工作台（改了服务端代码之后要用这个）
echo.

rem ── 1. 先关掉正在跑的那个（只关占用 8765 的进程，不动别的 python）────────────
set "PIDS="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"127.0.0.1:8765 .*LISTENING"') do set "PIDS=%%p"
if defined PIDS (
  echo  关掉旧的：PID %PIDS%
  for %%p in (%PIDS%) do taskkill /PID %%p /F >nul 2>&1
  rem 等端口真的放开（不 wait 的话新进程会因为端口占用挪到 8766，人会开错页）
  ping -n 3 127.0.0.1 >nul
) else (
  echo  没有发现正在跑的实例，直接启动。
)

rem ── 2. 启动新的（前台，关窗口即停）────────────────────────────────────────
echo.
echo  启动中… 浏览器打开 http://127.0.0.1:8765/
echo  第一次打开请按 Ctrl+Shift+R 强刷一次（不然浏览器可能还用着旧的界面代码）。
echo.
"%PYW%" server.py

echo.
echo  服务器已停止。
pause
