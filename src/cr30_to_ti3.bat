@echo off
setlocal
rem Run CR30 -> TI3 converter on Windows, keeping working dir at this folder
pushd "%~dp0"
set SCRIPT=%~dp0cr30_to_ti3.py

where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 "%SCRIPT%" %*
) else (
  python "%SCRIPT%" %*
)
set ERR=%ERRORLEVEL%
popd
exit /b %ERR%
