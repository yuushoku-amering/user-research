@echo off
rem ===========================================================================
rem  User Research Workbench - RESTART
rem
rem  Use this after changing server.py or anything under core\ -- those are
rem  loaded once at startup, so the browser refresh alone is not enough.
rem
rem  It kills whatever is listening on the port, then starts a fresh one.
rem  Closing the new window stops the service, same as the normal launcher.
rem
rem  PURE ASCII ON PURPOSE -- see the note in _find_engine.bat.
rem  The Python search order is shared with the launcher (_find_engine.bat).
rem ===========================================================================
setlocal
chcp 437 >nul 2>nul
cd /d "%~dp0"
title Restart User Research Workbench

set "PORT=8765"

echo.
echo   Restarting the workbench (needed after server-side code changes).
echo.

rem  /probe = find the python, report it, change nothing (used by the self-tests).
rem  It is checked BEFORE the kill step on purpose: a probe must not have
rem  side effects on whatever the user currently has running.
if /i "%~1"=="/probe" goto :probe

rem ---------- 1) kill whatever holds the port ----------
rem  Only touches a process that is LISTENING on 127.0.0.1:PORT --
rem  never any other python you may have running.
set "PIDS="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"127.0.0.1:%PORT% .*LISTENING"') do set "PIDS=%%p"
if defined PIDS (
  echo   Stopping the old instance: PID %PIDS%
  for %%p in (%PIDS%) do taskkill /PID %%p /F >nul 2>&1
  rem  Wait for the port to be really free.  Without this the new process
  rem  silently slides to the next port and the browser opens the wrong page.
  ping -n 3 127.0.0.1 >nul
) else (
  echo   Nothing was listening -- starting a fresh one.
)

:probe
rem ---------- 2) find a python ----------
echo.
call "%~dp0_find_engine.bat"
if not defined PYEXE goto :no_python

echo   Engine python: %PYEXE%
echo   Starting... the browser will open http://127.0.0.1:%PORT%/
echo   Press Ctrl+Shift+R once in the browser if the UI looks stale.
echo.

if /i "%~1"=="/probe" goto :done_ok

"%PYEXE%" server.py
echo.
echo   The service has stopped.
goto :done_ok

:no_python
echo   [!] No usable Python found (needs pandas / scipy / matplotlib).
echo       Run the normal launcher instead -- it prints the same hint plus
echo       the install command.  (See the Chinese manual for details.)

:done_ok
if /i "%~1"=="/probe" goto :eof
pause
endlocal
