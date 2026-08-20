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

echo.
echo Baudrate waehlen:
echo   1 = 115200
echo   2 = 230400
echo   3 = 460800  [empfohlen]
echo   4 = 921600
set /p "BAUD_CHOICE=Auswahl [3]: "
if not defined BAUD_CHOICE set "BAUD_CHOICE=3"

set "BAUD=460800"
if "%BAUD_CHOICE%"=="1" set "BAUD=115200"
if "%BAUD_CHOICE%"=="2" set "BAUD=230400"
if "%BAUD_CHOICE%"=="3" set "BAUD=460800"
if "%BAUD_CHOICE%"=="4" set "BAUD=921600"

echo.
echo Darstellung waehlen:
echo   1 = Pixel exakt
echo   2 = HD klar
set /p "MODE_CHOICE=Auswahl [1]: "
if not defined MODE_CHOICE set "MODE_CHOICE=1"

set "MODE=pixel"
if "%MODE_CHOICE%"=="2" set "MODE=hd"

where py >nul 2>nul
if errorlevel 1 (
  echo.
  echo FEHLER: Python-Launcher 'py' wurde nicht gefunden.
  echo Python von python.org installieren und 'Add Python to PATH' aktivieren.
  pause
  exit /b 1
)

echo.
echo Abhaengigkeiten installieren oder aktualisieren...
py -m pip install --user --upgrade pyserial pillow
if errorlevel 1 goto :failed

echo.
echo Display-Mirror starten...
echo Port: %PORT%   Baud: %BAUD%   Modus: %MODE%
py tactical_display_mirror.py "%PORT%" --baud %BAUD% --mode %MODE%
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo Display-Mirror wurde mit einem Fehler beendet.
pause
exit /b 1
