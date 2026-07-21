@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Jarnsen Tactical Display Mirror

echo ============================================================
echo JARNSEN TACTICAL DISPLAY MIRROR - WINDOWS
echo ============================================================
echo.
echo Tracker per USB verbinden und die Tactical-Seite anzeigen.
echo.
set /p "PORT=COM-Port eingeben, zum Beispiel COM5: "
if not defined PORT exit /b 1

where py >nul 2>nul
if errorlevel 1 (
  echo.
  echo FEHLER: Python-Launcher 'py' wurde nicht gefunden.
  echo Python von python.org installieren und 'Add Python to PATH' aktivieren.
  pause
  exit /b 1
)

echo.
echo PySerial installieren oder aktualisieren...
py -m pip install --user --upgrade pyserial
if errorlevel 1 goto :failed

echo.
echo Display-Mirror starten...
py tactical_display_mirror.py "%PORT%"
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo Display-Mirror wurde mit einem Fehler beendet.
pause
exit /b 1
