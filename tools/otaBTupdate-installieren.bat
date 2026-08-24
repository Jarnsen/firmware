@echo off
setlocal
title otaBTupdate sicher installieren

echo.
echo  otaBTupdate - einmalige USB-Installation
echo  Es wird nur die OTA-Partition bei 0x340000 beschrieben.
echo  Einstellungen, Kanaele, Schluessel und Logs bleiben erhalten.
echo.
set /p "JARNSEN_PORT=COM-Port eingeben (z.B. COM6): "
if not defined JARNSEN_PORT goto :error
if not exist "%~dp0otaBTupdate.bin" (
  echo FEHLER: otaBTupdate.bin fehlt neben dieser BAT-Datei.
  goto :error
)

where py >nul 2>nul
if errorlevel 1 (
  echo FEHLER: Python wurde nicht gefunden.
  echo Python 3 installieren und diese Datei erneut starten.
  goto :error
)

py -3 -m pip install --disable-pip-version-check esptool
if errorlevel 1 goto :error
py -3 -m esptool --chip esp32s3 --port "%JARNSEN_PORT%" write_flash 0x340000 "%~dp0otaBTupdate.bin"
if errorlevel 1 goto :error

echo.
echo ERFOLG: otaBTupdate wurde installiert. Nutzerdaten wurden nicht geloescht.
pause
exit /b 0

:error
echo.
echo Installation nicht abgeschlossen. Es wurden keine Loeschbefehle ausgefuehrt.
pause
exit /b 1
