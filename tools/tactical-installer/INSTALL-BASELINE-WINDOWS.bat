@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Jarnsen Heltec Wireless Tracker Baseline Installer

set "APP=Jarnsen-Baseline-Heltec-Wireless-Tracker-ESP32S3.bin"
set "BOOT=bootloader.bin"
set "PART=partitions.bin"
set "BOOT_APP0=boot_app0.bin"
set "OTA=mt-esp32s3-ota.bin"
set "LITTLEFS=littlefs.bin"

for %%F in ("%APP%" "%BOOT%" "%PART%" "%BOOT_APP0%" "%OTA%" "%LITTLEFS%") do (
  if not exist "%%~F" (
    echo.
    echo ERROR: Missing file: %%~F
    echo Extract the complete ZIP before starting this installer.
    pause
    exit /b 1
  )
)

echo ============================================================
echo JARNSEN BASELINE RECOVERY - HELTEC WIRELESS TRACKER ESP32-S3
echo ============================================================
echo.
echo WARNING: This performs a FULL ERASE.
echo Meshtastic settings, channels and stored data will be deleted.
echo.
echo This package contains the unmodified Meshtastic baseline build.
echo It does NOT contain the TacticalMap module.
echo.
set /p "PORT=Enter COM port, for example COM5: "
if not defined PORT exit /b 1

where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python launcher 'py' was not found.
  echo Install Python from python.org and enable Add Python to PATH.
  pause
  exit /b 1
)

echo.
echo Installing or updating esptool...
py -m pip install --user esptool==5.3.1
if errorlevel 1 goto :failed

echo.
echo Validating standalone application image...
for %%F in ("%APP%" "%OTA%") do if %%~zF GTR 3342336 goto :badimage
py -m esptool image-info "%APP%" | findstr /C:"Application Information" >nul
if errorlevel 1 goto :badimage
py -m esptool image-info "%APP%" | findstr /C:"Bootloader Information" >nul
if not errorlevel 1 goto :badimage
py -m esptool image-info "%APP%" | findstr /C:"ESP32-S3" >nul
if errorlevel 1 goto :badimage
py -m esptool image-info "%OTA%" | findstr /C:"Application Information" >nul
if errorlevel 1 goto :badimage
py -m esptool image-info "%OTA%" | findstr /C:"Bootloader Information" >nul
if not errorlevel 1 goto :badimage
py -m esptool image-info "%OTA%" | findstr /C:"ESP32-S3" >nul
if errorlevel 1 goto :badimage

echo.
echo Checking connected chip...
py -m esptool --chip esp32s3 --port "%PORT%" chip-id
if errorlevel 1 goto :boothelp

echo.
echo Erasing complete flash...
py -m esptool --chip esp32s3 --port "%PORT%" erase-flash
if errorlevel 1 goto :failed

echo.
echo Writing bootloader, partition table and application...
py -m esptool --chip esp32s3 --port "%PORT%" --baud 460800 write-flash ^
  0x0000 "%BOOT%" ^
  0x8000 "%PART%" ^
  0xe000 "%BOOT_APP0%" ^
  0x10000 "%APP%" ^
  0x340000 "%OTA%" ^
  0x670000 "%LITTLEFS%"
if errorlevel 1 goto :failed

echo.
echo SUCCESS. Disconnect USB briefly or press RESET.
echo This is only the boot-safe baseline test. Tactical functions are disabled.
pause
exit /b 0

:boothelp
echo.
echo The device was not detected in download mode.
echo Hold BOOT, tap RESET, release RESET, then release BOOT and retry.
pause
exit /b 1

:badimage
echo.
echo ERROR: The application BIN is not valid for offset 0x10000.
echo A factory or merged image must never be written at the application offset.
pause
exit /b 1

:failed
echo.
echo FLASH FAILED. Do not disconnect while a write is still active.
pause
exit /b 1
