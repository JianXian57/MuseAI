@echo off
setlocal

set "MUSE_ROOT=%~dp0"
set "MUSE_LAUNCHER=%MUSE_ROOT%tools\runtime\launcher.ps1"

if not exist "%MUSE_LAUNCHER%" (
    1>&2 echo MuseAI Launcher [LAUNCHER_NOT_FOUND] "%MUSE_LAUNCHER%" does not exist.
    exit /b 4
)

"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" ^
  -NoLogo ^
  -NoProfile ^
  -ExecutionPolicy Bypass ^
  -File "%MUSE_LAUNCHER%" %*

exit /b %ERRORLEVEL%
