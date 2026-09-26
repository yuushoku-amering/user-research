@echo off
chcp 65001 >nul
cd /d "%~dp0"
title User Research Workbench

rem ============================================================================
rem  用户研究工作台 · 启动器
rem
rem  它要找的是**一个带 pandas / scipy / matplotlib 的 Python**。
rem  找的顺序（先命中先用）：
rem    1. config.json 里写的 python
rem    2. 常见位置的自动探测（core\paths.py 里那份候选表）
rem    3. PATH 里的 python / py
rem  每一个候选都会**真的试着 import 一次 pandas**，能 import 才算数。
rem
rem  ⚠ 这个脚本原来是**写死某个 Python 绝对路径**的 —— 别人 clone 下来
rem     会直接「找不到引擎」。改成探测之后，换机器也能跑起来。
rem ============================================================================

set "PYEXE="
set "PROBE=%~dp0_jobs\_probe_python.py"

rem ---------- 1) 先问 config.json ----------
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "try{(Get-Content -Raw -Encoding UTF8 '%~dp0config.json' ^| ConvertFrom-Json).python}catch{''}"`) do set "CFG_PY=%%i"
if defined CFG_PY if exist "%CFG_PY%" (
  call :try_python "%CFG_PY%"
)

rem ---------- 2) 自动探测常见位置 ----------
if not defined PYEXE (
  for %%P in (
    "D:\GPT-SoVITS\GPT-SoVITS-v2pro-20250604\runtime\python.exe"
    "D:\ComfyUI_Windows_portable\python_standalone\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
  ) do (
    if not defined PYEXE if exist "%%~P" call :try_python "%%~P"
  )
)

rem ---------- 3) PATH 里的 python / py ----------
if not defined PYEXE (
  for %%C in (python.exe py.exe) do (
    if not defined PYEXE (
      for /f "delims=" %%W in ('where %%C 2^>nul') do (
        if not defined PYEXE call :try_python "%%W"
      )
    )
  )
)

if not defined PYEXE (
  echo.
  echo [!] 没找到能用的 Python。
  echo.
  echo     它需要带 pandas / scipy / matplotlib。装法（任选一种）：
  echo         pip install pandas scipy matplotlib openpyxl
  echo.
  echo     装好之后，二选一：
  echo       · 把那个 python.exe 的路径填进 config.json 的 "python" 一项
  echo         （可以先复制 config.example.json 改名成 config.json）
  echo       · 或者把它加进 PATH
  echo.
  pause
  exit /b 1
)

echo 引擎 Python：%PYEXE%
echo 启动工作台（**关掉这个窗口**就停服务）...
echo.
"%PYEXE%" server.py

echo.
echo 服务已停止。
pause
exit /b 0

rem ---------------------------------------------------------------------------
rem  试一个候选：能 import pandas 才算数
rem ---------------------------------------------------------------------------
:try_python
if not exist "%~1" exit /b 0
"%~1" -c "import pandas, scipy, matplotlib" >nul 2>nul
if errorlevel 1 (
  echo   [跳过] %~1 （缺 pandas / scipy / matplotlib）
  exit /b 0
)
set "PYEXE=%~1"
exit /b 0
