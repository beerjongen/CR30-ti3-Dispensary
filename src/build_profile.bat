@echo off
setlocal
rem Run profile builder on Windows, ensuring cwd = script folder
pushd "%~dp0"
set SCRIPT=%~dp0build_profile.py

where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 "%SCRIPT%" %*
) else (
  python "%SCRIPT%" %*
)
set ERR=%ERRORLEVEL%
popd
exit /b %ERR%
