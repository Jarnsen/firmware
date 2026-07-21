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
py -m pip install --user esptool==5.3.1
if errorlevel 1 (
  echo ERROR: esptool installation failed.
  pause
  exit /b 1
)

echo.
echo Validating standalone application image...
for %%F in ("Jarnsen-Tactical-Heltec-Wireless-Tracker-ESP32S3.bin") do if %%~zF GTR 3342336 goto :badimage
py -m esptool image-info "Jarnsen-Tactical-Heltec-Wireless-Tracker-ESP32S3.bin" | findstr /C:"Application Information" >nul
if errorlevel 1 goto :badimage
py -m esptool image-info "Jarnsen-Tactical-Heltec-Wireless-Tracker-ESP32S3.bin" | findstr /C:"Bootloader Information" >nul
if not errorlevel 1 goto :badimage
py -m esptool image-info "Jarnsen-Tactical-Heltec-Wireless-Tracker-ESP32S3.bin" | findstr /C:"ESP32-S3" >nul
if errorlevel 1 goto :badimage

set /p PORT=Enter COM port shown in Device Manager, for example COM5:
if "%PORT%"=="" (
  echo ERROR: No COM port entered.
  pause
  exit /b 1
)

echo.
echo Checking connected chip...
py -m esptool --chip esp32s3 --port "%PORT%" chip-id
if errorlevel 1 (
  echo.
  echo ERROR: No ESP32-S3 detected on %PORT%.
  echo Hold BOOT, press RESET once, release BOOT, then try again.
  pause
  exit /b 1
)

echo.
echo Flashing Tactical application firmware...
py -m esptool --chip esp32s3 --port "%PORT%" --baud 460800 write-flash 0x10000 "Jarnsen-Tactical-Heltec-Wireless-Tracker-ESP32S3.bin"
if errorlevel 1 (
  echo.
  echo ERROR: Flashing failed. Nothing else was erased.
  pause
  exit /b 1
)

echo.
echo SUCCESS. Disconnect and reconnect USB or press RESET.
echo Select role TRACKER or TAK_TRACKER to enable the Tactical screen.
echo If the display stays dark, restore official firmware with full erase.
pause
exit /b 0

:badimage
echo.
echo ERROR: The firmware BIN is not a standalone application image.
echo A factory or merged image must never be written at offset 0x10000.
pause
exit /b 1
