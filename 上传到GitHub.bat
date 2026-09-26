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
set "LOG=%~dp0push_log.txt"
set "RAW=%~dp0_jobs\push_raw.txt"

rem ---------- capture this run's output, so it survives the window ----------
rem  A previous run told us the console can disappear before it can be read.
rem  So: re-run ourselves through a redirect.  Everything this process writes
rem  lands in _jobs\push_raw.txt; the :done block staples it into push_log.txt
rem  together with the exact git/network settings.
rem  Output is still visible in the window at the same time.
rem  /logged marks the inner run so it does not recurse.
if /i not "%~1"=="/logged" (
  if not exist "%~dp0_jobs" mkdir "%~dp0_jobs" >nul 2>nul
  call "%~f0" /logged > "%RAW%" 2>&1
  goto :done
)

echo.
echo ================================================================
echo   Push this workbench to:
echo   %REPO%
echo ================================================================
echo.
echo   Everything below is also written to push_log.txt
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
rem  %GITROOT% comes from `where git`, so it keeps a ".." segment and the
rem  path reads as "F:\Git\cmd\..\mingw64\...".  That works, but it ends up in
rem  config.json and in the log, so resolve it to a clean absolute path.
if defined CA for %%I in ("%CA%") do set "CA=%%~fI"

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
echo.
echo ================================================================
echo   A copy of everything above is saved here:
echo     push_log.txt
echo   If the window closes before you can read it, open that file.
echo ================================================================

rem ---------- write the surviving log ----------
rem  Everything the script produced is captured in _jobs\push_raw.txt
rem  (stdout+stderr).  We then staple it into push_log.txt together with the
rem  exact git/network settings, so the whole story is in one place even if
rem  the console window vanishes.
set "RAW=%~dp0_jobs\push_raw.txt"

> "%LOG%" echo === User Research Workbench : push to GitHub ===
>>"%LOG%" echo time   : %DATE% %TIME%
>>"%LOG%" echo repo   : %REPO%
>>"%LOG%" echo proxy  : %PROXY%   (tried only if the direct route fails)
>>"%LOG%" echo python : (not used by this script)
>>"%LOG%" echo(
>>"%LOG%" echo --- git version ---
git --version >>"%LOG%" 2>&1
>>"%LOG%" echo(
>>"%LOG%" echo --- this repository's network settings ---
git config --local --get-regexp "^(http|credential|remote)\." >>"%LOG%" 2>&1
>>"%LOG%" echo(
>>"%LOG%" echo --- script output ---
if exist "%RAW%" type "%RAW%" >>"%LOG%" 2>&1
>>"%LOG%" echo(
>>"%LOG%" echo === end ===

del "%RAW%" >nul 2>nul

echo.
echo   (If this window keeps vanishing: open a Command Prompt yourself,
echo    cd to this folder, and run this same file from there -- that window
echo    will not close.  Or just read push_log.txt.)
echo.

rem  Optional belt-and-braces: `???GitHub.bat /keep` drops you into a
rem  shell in this folder instead of closing, for terminals that close their
rem  tab the moment the script exits (Windows Terminal does this by default).
if /i "%~1"=="/keep" (
  echo   Dropping into a shell.  Type EXIT to close it.
  endlocal
  cmd /k
) else (
  pause
  endlocal
)
