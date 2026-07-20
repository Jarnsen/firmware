@echo off
setlocal
title Jarnsen Tactical - Heltec Wireless Tracker ESP32-S3

echo ============================================================
echo JARNSEN TACTICAL UPDATE INSTALLER
echo Heltec Wireless Tracker - ESP32-S3 - UC6580 - SX1262
echo ============================================================
echo.
echo This updater writes ONLY the application firmware at 0x10000.
echo It keeps the official bootloader, partitions and filesystem intact.
echo Use it only after the official Heltec Wireless Tracker firmware boots.
echo.

if not exist "Jarnsen-Tactical-Heltec-Wireless-Tracker-ESP32S3.bin" (
  echo ERROR: Firmware BIN not found in this folder.
  pause
  exit /b 1
)

where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python launcher "py" was not found.
  echo Install Python 3 from python.org and enable Add Python to PATH.
  pause
  exit /b 1
)

echo Installing/updating esptool...
py -m pip install --user --upgrade esptool
if errorlevel 1 (
  echo ERROR: esptool installation failed.
  pause
  exit /b 1
)

set /p PORT=Enter COM port shown in Device Manager, for example COM5: 
if "%PORT%"=="" (
  echo ERROR: No COM port entered.
  pause
  exit /b 1
)

echo.
echo Checking connected chip...
py -m esptool --chip esp32s3 --port %PORT% chip-id
if errorlevel 1 (
  echo.
  echo ERROR: No ESP32-S3 detected on %PORT%.
  echo Hold BOOT, press RESET once, release BOOT, then try again.
  pause
  exit /b 1
)

echo.
echo Flashing Tactical application firmware...
py -m esptool --chip esp32s3 --port %PORT% --baud 460800 write-flash 0x10000 "Jarnsen-Tactical-Heltec-Wireless-Tracker-ESP32S3.bin"
if errorlevel 1 (
  echo.
  echo ERROR: Flashing failed. Nothing else was erased.
  pause
  exit /b 1
)

echo.
echo SUCCESS. Disconnect and reconnect USB or press RESET.
echo If the display stays dark, restore official firmware with full erase.
pause
