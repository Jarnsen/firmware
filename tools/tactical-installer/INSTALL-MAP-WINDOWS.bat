@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Jarnsen Tactical Map Update

echo ============================================================
echo JARNSEN TACTICAL MAP UPDATE - HELTEC WIRELESS TRACKER V1.1
echo ============================================================
echo.
echo This updates ONLY the LittleFS map/filesystem partition.
echo Firmware, NVS configuration, channels and device role are not erased.
echo A backup of the current LittleFS partition is created first.
echo.
if not exist "littlefs.bin" (
  echo ERROR: littlefs.bin is missing. Extract the complete firmware ZIP.
  pause
  exit /b 1
)

set /p "PORT=COM port, for example COM11: "
if not defined PORT exit /b 1

where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python launcher 'py' was not found.
  pause
  exit /b 1
)

py -m pip install --user --upgrade esptool==5.3.1
if errorlevel 1 goto :failed

set "BACKUP=littlefs-backup-%DATE:~-4%%DATE:~3,2%%DATE:~0,2%-%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%.bin"
set "BACKUP=%BACKUP: =0%"

echo.
echo Backing up current LittleFS partition...
py -m esptool --chip esp32s3 --port "%PORT%" read-flash 0x670000 0x190000 "%BACKUP%"
if errorlevel 1 goto :failed

echo.
echo Installing map filesystem...
py -m esptool --chip esp32s3 --port "%PORT%" write-flash --flash-mode dio --flash-freq 80m --flash-size 8MB 0x670000 littlefs.bin
if errorlevel 1 goto :restore_hint

echo.
echo SUCCESS: Map filesystem installed.
echo Backup: %BACKUP%
echo Restart the tracker and open the MAP FRI page.
pause
exit /b 0

:restore_hint
echo.
echo ERROR while writing the map filesystem.
echo The backup remains at: %BACKUP%
echo Do not delete it. It can be restored to address 0x670000.
pause
exit /b 1

:failed
echo.
echo Map update stopped before writing. The tracker was not changed.
pause
exit /b 1
