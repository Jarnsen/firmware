@echo off
setlocal
title Drone Repeater Flight Log Download
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo FEHLER: Python 3 wurde nicht gefunden.
  pause
  exit /b 1
)
py -3 "%~dp0DRONE_DIAG_LOG_DOWNLOADER.py"
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" echo Download nicht abgeschlossen. Fehlercode %RC%.
pause
exit /b %RC%
