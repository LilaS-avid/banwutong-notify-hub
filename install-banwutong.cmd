@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-shortcut.ps1"
if errorlevel 1 (
  echo.
  echo Installation failed. Review the message above.
) else (
  echo.
  echo Installation complete.
)
pause

