@echo off
rem ===========================================================================
rem  Find a usable Python for the workbench  -  SHARED SUBROUTINE
rem
rem  Usage:
rem      call "%~dp0_find_engine.bat"
rem      if not defined PYEXE goto :no_python
rem
rem  Used by BOTH launchers, so the search order lives in exactly one place.
rem  (It used to be duplicated, and one copy had a hard-coded absolute path --
rem   so "restart" worked only on the machine it was written on.)
rem
rem  Do NOT put "setlocal" in this file: it would throw away the discovery
rem  it exists to perform.  The calling script does setlocal.
rem
rem  PURE ASCII ON PURPOSE.  cmd.exe parses a .bat using the OEM code page
rem  (GBK on a Chinese Windows), so UTF-8 Chinese inside a .bat gets shredded
rem  into byte fragments that get executed as commands.
rem
rem  What it looks for: a python that can `import pandas, scipy, matplotlib`.
rem  Search order, first hit wins:
rem      1. the "python" value in config.json
rem      2. a list of common install locations
rem      3. python.exe / py.exe on PATH
rem ===========================================================================

set "PYEXE="
set "PROBE=%~dp0_jobs\_probe_python.py"

rem ---------- 0) the PORTABLE build's own python (highest priority) ----------
rem  The portable ZIP ships `_python\` next to the app folder, so from here it is
rem  `..\_python\python.exe`.  If it is there, USE IT, period -- that is the whole
rem  point of the portable build: do not depend on whatever the user happens to
rem  have installed.  (Without this, a machine that has its own Python would
rem  silently use that one instead, and "portable" would be a lie.)
if exist "%~dp0..\_python\python.exe" call :try_python "%~dp0..\_python\python.exe"

rem ---------- 1) ask config.json ----------
rem  The JSON reading lives in _read_config_python.ps1, NOT inline here.
rem  Inline PowerShell inside a for /f backquote needs ^| ^> escaping and
rem  nested quotes -- tried twice, and it either returned empty silently or
rem  failed to parse.  A separate file has nothing to escape.
rem
rem  The reason that file does not use `Get-Content -Encoding UTF8`:
rem  PowerShell 5.1 reads a BOM-less UTF-8 file as ANSI, so the Chinese in
rem  config.json becomes mojibake, ConvertFrom-Json throws, the error gets
rem  swallowed, and the launcher SILENTLY ignores the python you configured
rem  and picks another one off PATH.  Exactly the "works, but not with what
rem  you asked for" bug class this project exists to avoid.
rem
rem  NOTE: A RELATIVE path in config.json is resolved against THIS folder (%~dp0),
rem  not against the current directory -- the portable config says
rem  `..\_python\python.exe`, which only means anything relative to the app dir.
if not defined PYEXE (
  for /f "usebackq delims=" %%i in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_read_config_python.ps1"`) do set "CFG_PY=%%i"
  if defined CFG_PY if not exist "%CFG_PY%" if exist "%~dp0%CFG_PY%" set "CFG_PY=%~dp0%CFG_PY%"
  if defined CFG_PY if exist "%CFG_PY%" call :try_python "%CFG_PY%"
)

rem ---------- 2) probe common locations ----------
if not defined PYEXE (
  for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "D:\GPT-SoVITS\GPT-SoVITS-v2pro-20250604\runtime\python.exe"
    "D:\ComfyUI_Windows_portable\python_standalone\python.exe"
  ) do (
    if not defined PYEXE if exist "%%~P" call :try_python "%%~P"
  )
)

rem ---------- 3) whatever is on PATH ----------
if not defined PYEXE (
  for %%C in (python.exe py.exe) do (
    if not defined PYEXE (
      for /f "delims=" %%W in ('where %%C 2^>nul') do (
        if not defined PYEXE call :try_python "%%W"
      )
    )
  )
)

rem ---------- 4) last resort: `py -3` launcher ----------
if not defined PYEXE (
  for /f "delims=" %%W in ('where py.exe 2^>nul') do (
    if not defined PYEXE (
      "%%W" -3 -c "import pandas, scipy, matplotlib" >nul 2>nul
      if not errorlevel 1 set "PYEXE=%%W -3"
    )
  )
)

goto :eof

rem ---------------------------------------------------------------------------
rem  try one candidate: only counts if it can really import the libraries
rem ---------------------------------------------------------------------------
:try_python
if not exist "%~1" exit /b 0
"%~1" -c "import pandas, scipy, matplotlib" >nul 2>nul
if errorlevel 1 (
  echo   [skip] %~1  -- missing pandas / scipy / matplotlib
  exit /b 0
)
set "PYEXE=%~1"
exit /b 0
