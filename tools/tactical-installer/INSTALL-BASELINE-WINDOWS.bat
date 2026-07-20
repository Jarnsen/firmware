@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Jarnsen Heltec Wireless Tracker Baseline Installer

set "APP=Jarnsen-Baseline-Heltec-Wireless-Tracker-ESP32S3.bin"
set "BOOT=bootloader.bin"
set "PART=partitions.bin"

for %%F in ("%APP%" "%BOOT%" "%PART%") do (
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
py -m pip install --user --upgrade esptool
if errorlevel 1 goto :failed

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
  0x10000 "%APP%"
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

:failed
echo.
echo FLASH FAILED. Do not disconnect while a write is still active.
pause
exit /b 1
