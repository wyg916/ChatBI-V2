@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1"
set "CHATBI_EXIT_CODE=%ERRORLEVEL%"

if not "%CHATBI_EXIT_CODE%"=="0" (
  echo.
  echo Startup failed. Review the message above, then press any key to close.
  pause >nul
)

exit /b %CHATBI_EXIT_CODE%
