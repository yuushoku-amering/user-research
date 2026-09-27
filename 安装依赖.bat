@echo off
rem ===========================================================================
rem  LanTai Vesper - install the Python packages this workbench needs
rem
rem  Double-click this file. It finds a Python, installs what requirements.txt
rem  asks for, then checks that everything really imports.
rem
rem  When to use this
rem  ----------------
rem  Only for the SOURCE version. If you downloaded the portable build (the one
rem  with a _python\ folder in it), you do NOT need this -- Python and every
rem  package are already inside that folder.
rem
rem  PURE ASCII ON PURPOSE. A .bat is parsed with the OEM code page (GBK on a
rem  Chinese Windows), so a UTF-8 Chinese byte inside it -- even in a comment --
rem  gets shredded into fragments that then get executed as commands. That
rem  includes passing a Chinese FILENAME or FOLDER to another program: cmd
rem  mangles the path and reports "cannot find the file".
rem
rem  This is why the helper script sits right here next to this file and has an
rem  ASCII name (_install_deps.py). The Chinese report it writes is UTF-8 and
rem  never goes through the command line.
rem
rem  (This mistake was made three times while writing the build scripts.
rem   Keep this file 100%% ASCII. No exceptions.)
rem ===========================================================================
setlocal
chcp 437 >nul 2>nul
cd /d "%~dp0"
title LanTai Vesper - install packages

rem ---- find a Python (same search order as _find_engine.bat) ----
set "PY="
for %%P in (
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
  "C:\Python313\python.exe"
  "C:\Python312\python.exe"
  "C:\Python311\python.exe"
  "C:\Python310\python.exe"
) do (
  if not defined PY if exist "%%~P" set "PY=%%~P"
)
if not defined PY (
  for %%C in (python.exe py.exe) do (
    if not defined PY (
      for /f "delims=" %%W in ('where %%C 2^>nul') do (
        if not defined PY set "PY=%%W"
      )
    )
  )
)

if not defined PY goto :nopy

echo.
echo   Using: %PY%
echo.

"%PY%" "%~dp0_install_deps.py" %*
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" goto :maybe_failed

echo   All set. Next: double-click the launcher script in this folder.
echo.
goto :done

:maybe_failed
echo ================================================================
echo   Something is still missing (exit code %RC%).
echo ================================================================
echo.
echo   Read the messages above -- pip prints the real reason there.
echo   A plain-text report was also written next to this file, named
echo   install-report.txt  (UTF-8; if Notepad shows garbage, open it with
echo   VS Code or WordPad, or just read the window above).
echo.
echo   Most common cause: pip tried to COMPILE a package because the
echo   installed Python is too new and has no prebuilt wheel yet.
echo   Fix: install Python 3.11 or 3.12 and run this file again.
echo.

:nopy
if not defined PY (
  echo.
  echo   [!] No Python found.
  echo.
  echo       Install Python 3.12 from https://www.python.org/downloads/
  echo       and TICK "Add python.exe to PATH" during setup.
  echo       Then double-click this file again.
  echo.
  echo   (Or use the PORTABLE build instead -- it needs no installation.)
  echo.
)
goto :done

:done
echo.
pause
endlocal
