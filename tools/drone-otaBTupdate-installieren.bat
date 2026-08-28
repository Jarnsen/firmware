@echo off
setlocal
title Drone Repeater Bluetooth-OTA installieren

echo.
echo  Drone Repeater Bluetooth-OTA - einmalige USB-Erstinstallation
echo  Hauptfirmware: 0x10000  /  otaBTupdate: 0x340000
echo  Einstellungen, Kanaele, Schluessel und Flight-Logs bleiben erhalten.
echo.
set /p "JARNSEN_PORT=COM-Port eingeben (z.B. COM6): "
if not defined JARNSEN_PORT goto :error
if not exist "%~dp0otaBTupdate.bin" (
  echo FEHLER: otaBTupdate.bin fehlt neben dieser BAT-Datei.
  goto :error
)
if not exist "%~dp0heltec-tracker-v11-drone-repeater.update.bin" (
  echo FEHLER: heltec-tracker-v11-drone-repeater.update.bin fehlt neben dieser BAT-Datei.
  goto :error
)

where py >nul 2>nul
if errorlevel 1 (
  echo FEHLER: Python 3 wurde nicht gefunden.
  goto :error
)

py -3 -m pip install --disable-pip-version-check esptool
if errorlevel 1 goto :error
py -3 -m esptool --chip esp32s3 --port "%JARNSEN_PORT%" write-flash ^
  0x10000 "%~dp0heltec-tracker-v11-drone-repeater.update.bin" ^
  0x340000 "%~dp0otaBTupdate.bin"
if errorlevel 1 goto :error
py -3 -m esptool --chip esp32s3 --port "%JARNSEN_PORT%" erase-region 0xE000 0x2000
if errorlevel 1 goto :error

echo.
echo ERFOLG: Drone-Firmware und otaBTupdate wurden installiert.
echo OTA-Bootwahl wurde auf die Hauptfirmware zurueckgesetzt.
echo Nutzerdaten und Flight-Logs wurden nicht geloescht.
pause
exit /b 0

:error
echo.
echo Installation nicht abgeschlossen. Nutzerdaten wurden nicht geloescht.
pause
exit /b 1
