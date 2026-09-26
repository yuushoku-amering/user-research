@echo off
rem ===========================================================================
rem  User Research Workbench - push to GitHub
rem  (script version 3)
rem
rem  PURE ASCII ON PURPOSE.  cmd.exe parses a .bat using the OEM code page
rem  (GBK on a Chinese Windows), so UTF-8 Chinese inside a .bat gets shredded
rem  into byte fragments that then get executed as commands.
rem
rem  DESIGN NOTE - why this does NOT re-run itself:
rem  Version 2 re-ran this file with its output redirected, to capture a log.
rem  That was a mistake: the redirect swallowed the child's output INCLUDING
rem  the "Press any key" prompt, so the window sat there blank and looked
rem  frozen.  Now everything happens in this one process and stays on screen.
rem ===========================================================================
setlocal
chcp 437 >nul 2>nul
cd /d "%~dp0"
title Push to GitHub

set "REPO=https://github.com/yuushoku-amering/user-research.git"
set "PROXY=http://127.0.0.1:7897"
set "LOG=%~dp0push_log.txt"
set "ERRF=%TEMP%\urw_git_err.txt"

echo.
echo ================================================================
echo   Push this workbench to:
echo   %REPO%
echo ================================================================
echo.

where git >nul 2>nul
if errorlevel 1 goto :nogit

rem ---------- locate the CA bundle that ships with git ----------
rem  git's default schannel trust store fails on some machines with
rem  SEC_E_NO_CREDENTIALS, so we use its OpenSSL backend plus this bundle.
set "GITROOT="
for /f "delims=" %%G in ('where git 2^>nul') do (
  if not defined GITROOT set "GITROOT=%%~dpG.."
)
set "CA="
if defined GITROOT if exist "%GITROOT%\mingw64\etc\ssl\certs\ca-bundle.crt" set "CA=%GITROOT%\mingw64\etc\ssl\certs\ca-bundle.crt"
if not defined CA if exist "F:\Git\mingw64\etc\ssl\certs\ca-bundle.crt" set "CA=F:\Git\mingw64\etc\ssl\certs\ca-bundle.crt"
if defined CA for %%I in ("%CA%") do set "CA=%%~fI"

echo [1/5] git found.
echo       CA bundle: %CA%
if not defined CA echo       WARNING: no ca-bundle found - TLS may fail.

rem ---------- per-repo network settings (your global config is untouched) ----------
git config http.sslBackend openssl
if defined CA git config http.sslCAInfo "%CA%"
git config credential.helper manager
git config --unset http.lowSpeedLimit >nul 2>nul
git config --unset http.lowSpeedTime  >nul 2>nul

rem ---------- remote ----------
echo.
git remote get-url origin >nul 2>nul
if errorlevel 1 (
  echo [2/5] No remote yet - adding it.
  git remote add origin "%REPO%"
) else (
  echo [2/5] Remote already set.
)

rem ---------- commit anything pending ----------
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

rem ---------- can we reach GitHub? (do this BEFORE asking to sign in) ----------
echo.
echo [4/5] Testing the connection to GitHub...
git ls-remote --heads origin > "%TEMP%\urw_remote.txt" 2> "%ERRF%"

if errorlevel 1 (
  echo       Direct connection failed. Retrying through the local proxy...
  git config http.proxy "%PROXY%"
  git ls-remote --heads origin > "%TEMP%\urw_remote.txt" 2> "%ERRF%"
)

if errorlevel 1 (
  echo.
  echo ================================================================
  echo   CANNOT REACH GITHUB - stopping here so we do not waste a
  echo   sign-in on a connection that will not work anyway.
  echo ================================================================
  echo.
  echo   Is Clash / your VPN running?  This script tried:
  echo     - a direct connection
  echo     - the local proxy at %PROXY%
  echo.
  echo   Last error from git:
  echo ----------------------------------------------------------------
  type "%ERRF%"
  echo ----------------------------------------------------------------
  goto :done
)

echo       OK - reached GitHub.
for %%A in ("%TEMP%\urw_remote.txt") do if %%~zA EQU 0 echo       (the remote is empty - this is the first push)

rem ---------- sign in + push ----------
echo.
echo [5/5] Sign-in and push
echo.
echo   If a browser window pops up, log in and authorize.
echo.
echo   IF it asks for a password in THIS console instead:
echo     your GitHub account password will NOT work.
echo     Make a Personal Access Token and paste THAT as the password:
echo       https://github.com/settings/tokens
echo       -^> Generate new token (classic)  -^> tick "repo"
echo.
echo ----------------------------------------------------------------
git push -u origin main 2>&1
set "RC=%ERRORLEVEL%"
echo ----------------------------------------------------------------
echo.

if not "%RC%"=="0" goto :failed

echo ================================================================
echo   SUCCESS - the workbench is on GitHub.
echo ================================================================
echo.
echo   Open it here:
echo     https://github.com/yuushoku-amering/user-research
echo.
echo   What is up there: the SOFTWARE ONLY.
echo   No research projects, no test fixtures, no config.json.
echo.
echo   Network settings that were needed on this machine (saved as LOCAL
echo   repo config, so your other repositories are unaffected):
echo     sslBackend = openssl    - the default schannel backend fails here
echo     sslCAInfo  = %CA%
echo     proxy      = %PROXY%   (only if the direct route failed)
echo   To undo the proxy setting:   git config --unset http.proxy
goto :done

:failed
echo ================================================================
echo   FAILED  (git returned %RC%)
echo ================================================================
echo.
echo   What the usual causes look like:
echo.
echo   Authentication failed / 403
echo     You typed your account password. GitHub needs a Personal Access
echo     Token (link above), not your password.
echo.
echo   rejected / fetch first
echo     The remote already has commits. When you created the repo, did you
echo     tick "Add a README"?  If so, tell Yuu and she will sort it out.
echo.
echo   Could not connect / timeout
echo     Network again. Check the VPN.
echo.
echo   Scroll up for git's own message - it says which one it is.
goto :done

:nogit
echo [!] git was not found.
echo     Install it first: https://git-scm.com/download/win
echo     Then run this script again.

:done
rem ---------- write a small log of this run ----------
> "%LOG%" echo === workbench push log ===
>>"%LOG%" echo time : %DATE% %TIME%
>>"%LOG%" echo repo : %REPO%
>>"%LOG%" echo(
>>"%LOG%" echo --- this repository's network settings ---
git config --local --get-regexp "^(remote|http|credential)\." >>"%LOG%" 2>&1
>>"%LOG%" echo(
>>"%LOG%" echo --- what is on the remote right now ---
git ls-remote --heads origin >>"%LOG%" 2>&1

echo.
echo ================================================================
echo   A short summary of this run is in push_log.txt
echo   (network settings + what is currently on the remote)
echo ================================================================
echo.

rem  /nopause is used by the "keep the window open" wrapper in this folder.
rem  That wrapper already holds the window with `cmd /k`, so a second
rem  "press any key" would just be a confusing extra step.
rem
rem  The wrapper's filename is deliberately NOT written here: this file must be
rem  saved as ASCII for cmd to parse it, and Chinese text saved as ASCII turns
rem  into "?" -- which already broke the wrapper's own call line once.
if /i "%~1"=="/nopause" goto :eof

rem  On Windows Terminal this tab closes as soon as the script ends, so pressing
rem  a key here can look like "it crashed". It did not -- scroll up, the output
rem  is all there, and push_log.txt has a copy.
echo   Press any key to close this window.
echo   (If it closes and you want to read the output again: push_log.txt)
echo.
pause
endlocal
