@echo off
rem ===========================================================================
rem  Push to GitHub  --  keep the window open afterwards
rem
rem  WHY THIS EXISTS
rem  The normal launcher ends with `pause`, which waits for a key press. That
rem  works -- but on Windows Terminal the tab closes the moment the script
rem  ends, so pressing a key looks like "it crashed and vanished".
rem  Nothing is wrong when that happens; the output was already on screen and
rem  the push already finished.
rem
rem  This wrapper opens a new console that runs the push script and then STAYS
rem  OPEN (it drops into a shell instead of exiting). Read the output, scroll
rem  back, then type EXIT.
rem
rem  === THREE RULES LEARNED THE HARD WAY, KEEP THEM ===
rem
rem  1. PURE ASCII ONLY. Non-ASCII inside a .bat gets shredded by the OEM code
rem     page (see the note in _find_engine.bat).
rem
rem  2. NEVER WRITE THE CHINESE SCRIPT NAME IN THIS FILE, not even in a
rem     comment. The file must be saved as ASCII for cmd to parse it, and
rem     saving Chinese *as* ASCII silently turns it into "?". That already
rem     broke this wrapper once -- the call line came out as
rem     `call .\???GitHub.bat` and could never have run.
rem
rem  3. NEVER PUT A NON-ASCII PATH ON A COMMAND LINE (`cmd /k "..."`).
rem     This one cost the most time. The wrapper used to resolve the script
rem     with a wildcard and pass the full path to `cmd /k`; that path contains
rem     Chinese, and cmd rebuilt it under the console code page on the way in,
rem     so the child got a corrupted path -- it even created a stray file
rem     named "resolved" in the repository. A path on a command line is not
rem     safe here. `cd` IS inherited by a child process, so the child simply
rem     starts in the right folder and only ever sees a relative name.
rem ===========================================================================
setlocal
chcp 437 >nul 2>nul
cd /d "%~dp0"

rem Find the push script by its ASCII suffix; call it by BARE NAME so that no
rem path (and therefore no non-ASCII text) travels on a command line.
set "PUSHNAME="
for %%F in ("*GitHub.bat") do if not defined PUSHNAME set "PUSHNAME=%%~nxF"

if not defined PUSHNAME (
  echo.
  echo   [!] Cannot find the push script ^(a file ending in GitHub.bat^)
  echo       in this folder. Is it still there?
  echo.
  pause
  exit /b 1
)

echo.
echo ================================================================
echo   Pushing to GitHub.
echo   A new window will open and will STAY OPEN when it finishes.
echo.
echo   It starts in this folder and runs the script whose name ends
echo   in GitHub.bat  (the full name is shown in that window, not
echo   here -- see rule 2 in this file).
echo ================================================================
echo.

rem `start` so this console is not blocked. The child inherits our working
rem directory, which is all it needs to find the script.
start "Push to GitHub" cmd /k call %PUSHNAME%

endlocal
