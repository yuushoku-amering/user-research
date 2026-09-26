@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 上传到 GitHub

rem ============================================================================
rem  用户研究工作台 · 一键上传到 GitHub
rem
rem  为什么需要你亲手点一下：
rem    AI 助手的那个环境里 git 连不上 GitHub（系统 TLS 拿不到凭据，
rem    这是那台机器上的老毛病，不是网络不通）。你自己双击就跑得通。
rem
rem  这个脚本会做四件事：
rem    1. 确认 remote 指向你的仓库
rem    2. 让你登录一次 GitHub（浏览器弹窗，登录一次以后就不用再登）
rem    3. 推上去
rem    4. 把结果和仓库地址打出来
rem ============================================================================

set "REPO=https://github.com/yuushoku-amering/user-research.git"

echo.
echo ================================================================
echo   把这个工作台推到 %REPO%
echo ================================================================
echo.

rem ---------- 0) git 在不在 ----------
where git >nul 2>nul
if errorlevel 1 (
  echo [!] 找不到 git。先装一个：https://git-scm.com/download/win
  echo     装完把电脑重启一下再双击本脚本。
  goto :end
)

rem ---------- 1) 确认 remote ----------
git remote get-url origin >nul 2>nul
if errorlevel 1 (
  echo [1/4] 还没有 remote，现在加上
  git remote add origin "%REPO%"
) else (
  echo [1/4] remote 已经是：
  git remote -v
)

rem ---------- 2) 本地先提交干净 ----------
echo.
echo [2/4] 检查有没有没提交的改动
git status --porcelain > "%TEMP%\urw_dirty.txt"
for %%A in ("%TEMP%\urw_dirty.txt") do if %%~zA GTR 0 (
  echo     有改动还没提交，先提交一下（信息用默认的，你之后可以改）
  git add -A
  git commit -m "上传前的一次提交"
) else (
  echo     干净，没有未提交的改动
)

rem ---------- 3) 设置凭据助手（登录一次，以后不用再登） ----------
echo.
echo [3/4] 准备 GitHub 登录
echo     如果弹出浏览器窗口，登录你的 GitHub 账号并授权即可。
echo     如果弹的是命令行让你输用户名密码 ——
echo       密码那一栏**不能填账号密码**，要填 Personal Access Token
echo       （GitHub 早就不让用密码推代码了）。申请地址：
echo       https://github.com/settings/tokens  →  Generate new token (classic)
echo       →  勾上 repo  →  生成后复制那一串，粘进来当密码。
echo.
git config --global credential.helper manager

rem ---------- 4) 推 ----------
echo.
echo [4/4] 开始推送...
echo.
git push -u origin main
set "RC=%ERRORLEVEL%"

echo.
echo ================================================================
if "%RC%"=="0" (
  echo   ✅ 推上去了！去这里看：
  echo      https://github.com/yuushoku-amering/user-research
  echo.
  echo   注意：仓库里**只有软件本体**，你那些研究项目一个都没进去
  echo         （config.json、_jobs、dsh-home、libs 也都没进去）。
) else (
  echo   ❌ 没推成功（退出码 %RC%）
  echo.
  echo   常见原因，照着看：
  echo     · Authentication failed / 403
  echo         → 密码位置填成了账号密码。要在
  echo           https://github.com/settings/tokens 申请 token（勾 repo）当密码用
  echo     · Could not connect to server / timeout
  echo         → 网络问题。开着梯子再试，或者换手机热点
  echo     · remote origin already exists
  echo         → 不用管，脚本已经处理了
  echo     · rejected / fetch first
  echo         → 远端已经有东西了（建仓库时勾了 README？）
  echo           双击 `重启工作台.bat` 旁边的办法没用，直接找鱼鱼
  echo.
  echo   把上面的报错整段复制给鱼鱼，她知道怎么处理。
)
echo ================================================================
echo.

:end
pause
