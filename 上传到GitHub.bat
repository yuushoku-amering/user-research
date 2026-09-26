@echo off
rem ===========================================================================
rem  User Research Workbench - push to GitHub
rem
rem  This file is deliberately PURE ASCII (no Chinese, no emoji).
rem  Why: cmd.exe reads a .bat using the machine's OEM code page (GBK here),
rem  so UTF-8 Chinese inside a .bat gets shredded and the fragments get
rem  executed as commands.  That is what broke the first version.
rem
rem  It also sets up the network bits that this machine specifically needs --
rem  see the "WHY THESE SETTINGS" note further down.
rem ===========================================================================
setlocal
chcp 437 >nul 2>nul
cd /d "%~dp0"
title Push to GitHub

set "REPO=https://github.com/yuushoku-amering/user-research.git"
set "PROXY=http://127.0.0.1:7897"

echo.
echo ================================================================
echo   Push this workbench to:
echo   %REPO%
echo ================================================================
echo.

rem ---------- 0) git present? ----------
where git >nul 2>nul
if errorlevel 1 goto :nogit

rem ---------- 0b) locate the CA bundle shipped with git ----------
rem  git on this machine has no usable default trust store (schannel fails
rem  with SEC_E_NO_CREDENTIALS), so we use its OpenSSL backend plus the
rem  ca-bundle that ships with the installation.
set "GITROOT="
for /f "delims=" %%G in ('where git 2^>nul') do (
  if not defined GITROOT set "GITROOT=%%~dpG.."
)
set "CA="
if defined GITROOT if exist "%GITROOT%\mingw64\etc\ssl\certs\ca-bundle.crt" set "CA=%GITROOT%\mingw64\etc\ssl\certs\ca-bundle.crt"
if not defined CA if exist "F:\Git\mingw64\etc\ssl\certs\ca-bundle.crt" set "CA=F:\Git\mingw64\etc\ssl\certs\ca-bundle.crt"

echo [1/5] git found.  CA bundle: %CA%
if not defined CA echo       WARNING: no ca-bundle found - the push may fail on TLS.

rem ---------- 1c) per-repo network settings (does NOT touch your global config) ----------
git config http.sslBackend openssl
if defined CA git config http.sslCAInfo "%CA%"
git config http.proxy "%PROXY%"
git config credential.helper manager
git config --unset http.lowSpeedLimit >nul 2>nul
git config --unset http.lowSpeedTime  >nul 2>nul

rem ---------- 1) remote ----------
echo.
git remote get-url origin >nul 2>nul
if errorlevel 1 (
  echo [2/5] No remote yet - adding it.
  git remote add origin "%REPO%"
) else (
  echo [2/5] Remote already set:
  git remote -v
)

rem ---------- 2) commit anything pending ----------
echo.
echo [3/5] Checking for uncommitted changes...
git status --porcelain > "%TEMP%\urw_dirty.txt" 2>nul
for %%A in ("%TEMP%\urw_dirty.txt") do if %%~zA GTR 0 (
  echo       Found changes - committing them first.
  git add -A
  git commit -m "push pending changes"
) else (
  echo       Clean - nothing to commit.
)

rem ---------- 3) can we reach GitHub at all? ----------
echo.
echo [4/5] Testing the connection to GitHub...
git ls-remote --heads origin > "%TEMP%\urw_remote.txt" 2>"%TEMP%\urw_remote_err.txt"
if errorlevel 1 (
  echo       Proxy did not work. Trying a direct connection...
  git config --unset http.proxy
  git ls-remote --heads origin >nul 2>"%TEMP%\urw_remote_err.txt"
  if errorlevel 1 (
    echo.
    echo   FAILED - cannot reach GitHub.
    echo   Error was:
    type "%TEMP%\urw_remote_err.txt"
    echo.
    echo   Check: is the VPN / Clash running?  Port 7897 should be listening.
    echo   Copy the error above and send it back.
    goto :done
  )
  echo       Direct connection works.
) else (
  echo       OK - reached GitHub through the proxy.
)

rem ---------- 4) sign-in + push ----------
echo.
echo [5/5] Sign-in and push
echo.
echo   A browser window may pop up. Log in and authorize.
echo.
echo   IF it asks for a password in this console instead:
echo     your GitHub account password will NOT work.
echo     Make a Personal Access Token and paste THAT as the password:
echo       https://github.com/settings/tokens
echo       -^> Generate new token (classic)  -^> tick "repo"
echo.
git push -u origin main
set "RC=%ERRORLEVEL%"

echo.
echo ================================================================
if "%RC%"=="0" goto :pushed
echo   FAILED  (exit code %RC%)
echo.
echo   Authentication failed / 403
echo     - you typed your account password. Use a token (link above).
echo   rejected / fetch first
echo     - the remote already has commits. Did you tick "Add a README"
echo       when creating the repo?  Send the whole error to Yuu.
echo   Could not connect / timeout
echo     - network again. Check the VPN.
echo.
echo   Copy the whole error text above and send it back.
goto :done

:pushed
echo   DONE - pushed successfully.
echo.
echo   Open it here:
echo     https://github.com/yuushoku-amering/user-research
echo.
echo   Note: the repository contains the SOFTWARE ONLY.
echo         No research projects, no test fixtures, no config.
echo.
echo   Why these settings (for the record):
echo     sslBackend=openssl + ca-bundle  - git's default schannel trust
echo       store fails on this machine with SEC_E_NO_CREDENTIALS
echo     http.proxy=127.0.0.1:7897        - a direct connection stalls
echo   They are stored as LOCAL repo config, so your other repos are
echo   unaffected.  To undo:  git config --unset http.proxy
goto :done

:nogit
echo [!] git was not found.
echo     Install it first: https://git-scm.com/download/win
echo     Then restart this script.
goto :done

:done
echo ================================================================
echo.
pause
endlocal
