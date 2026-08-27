@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\showcase.ps1" -Action Start
set "CHATBI_EXIT_CODE=%ERRORLEVEL%"

if not "%CHATBI_EXIT_CODE%"=="0" (
  echo.
  echo Showcase startup failed. Review the message above, then press any key to close.
  pause >nul
)

exit /b %CHATBI_EXIT_CODE%
