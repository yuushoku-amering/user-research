@echo off
rem ===========================================================================
rem  User Research Workbench - LAUNCHER
rem
rem  Double-click this. Close the window to stop the service.
rem
rem  PURE ASCII ON PURPOSE -- see the note in _find_engine.bat.
rem  The Python search order lives in _find_engine.bat (shared with the
rem  restart script), so there is exactly one copy of it.
rem ===========================================================================
setlocal
chcp 437 >nul 2>nul
cd /d "%~dp0"
title User Research Workbench

call "%~dp0_find_engine.bat"

if not defined PYEXE goto :no_python

echo.
echo   Engine python: %PYEXE%
echo   Starting the workbench. CLOSE THIS WINDOW to stop it.
echo.

rem  /probe = just show which python was found and exit (used by the self-tests)
if /i "%~1"=="/probe" goto :done_ok

"%PYEXE%" server.py
echo.
echo   The service has stopped.
goto :done_ok

:no_python
echo.
echo   [!] No usable Python found.
echo.
echo       It needs pandas / scipy / matplotlib. Install them with:
echo           pip install pandas scipy matplotlib openpyxl
echo.
echo       Then do ONE of these:
echo         * put that python.exe path into config.json  ("python")
echo           (copy config.example.json to config.json first)
echo         * or add it to PATH
echo.
echo       The Chinese manual has the same instructions (see the .md files).

:done_ok
if /i "%~1"=="/probe" goto :eof
pause
endlocal
