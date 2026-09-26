@echo off
rem ===========================================================================
rem  User Research Workbench - 5-minute demo (no browser needed)
rem
rem  PURE ASCII ON PURPOSE.  Scripts with a .bat extension get parsed using the
rem  OEM code page (GBK on a Chinese Windows), so non-ASCII text inside them is
rem  shredded into byte fragments that then get executed as commands.
rem  The Chinese explanation lives in _demo.py, where Python handles the
rem  encoding properly.
rem ===========================================================================
setlocal
chcp 437 >nul 2>nul
cd /d "%~dp0"
title Workbench demo

rem ---------- find a python with the libraries we need ----------
call "%~dp0_find_engine.bat"

if not defined PYEXE goto :nopy

echo.
echo   Python: %PYEXE%
echo   Running the demo...  (usually finishes in a few seconds)
echo.

"%PYEXE%" -X utf8 "%~dp0_demo.py"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" goto :failed
goto :done

:failed
echo ================================================================
echo   The demo did not finish (exit code %RC%).
echo ================================================================
echo.
echo   Scroll up for the reason, or send the text to Yuu.
goto :done

:nopy
echo.
echo   [!] No usable Python found.
echo.
echo       The demo needs pandas / scipy / matplotlib. Install with:
echo           pip install pandas scipy matplotlib openpyxl
echo.
echo       Then run this file again.
echo.

:done
echo.
pause
endlocal
