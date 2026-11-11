@echo off
rem Weekly digest, curation and toast. Run by the scheduled task \WorkLedger\WeeklyDigest.
rem Usage: weekly.cmd [PYTHON]   (default: python on PATH)
rem Output is appended to out\weekly.log under the project root.
setlocal
set "PY=%~1"
if "%PY%"=="" set "PY=python"
cd /d "%~dp0.." || exit /b 1
if not exist "out" mkdir "out" || exit /b 1
set "PYTHONPATH=src"
echo [%DATE% %TIME%] weekly start >> "out\weekly.log"
"%PY%" -m work_ledger weekly >> "out\weekly.log" 2>&1
set "CODE=%ERRORLEVEL%"
echo [%DATE% %TIME%] weekly exit %CODE% >> "out\weekly.log"
exit /b %CODE%
