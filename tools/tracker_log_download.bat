@echo off
setlocal
title Tracker V1.1 Diagnostic Log Download
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  set "PY=python"
)

%PY% -c "import serial" >nul 2>nul
if not %errorlevel%==0 (
  echo Installing pyserial for the Tracker log downloader...
  %PY% -m pip install --user pyserial
  if not %errorlevel%==0 (
    echo.
    echo Could not install pyserial. Install Python 3 and run again.
    echo.
    pause
    exit /b 2
  )
)

echo ========================================
echo          TRACKER LOG DOWNLOAD
echo ========================================
echo.
%PY% TRACKER_V11_DIAG_LOG_DOWNLOADER.py %*
set "RC=%errorlevel%"
echo.
if "%RC%"=="0" (
  echo Download finished successfully.
) else (
  echo Download ended with error code %RC%.
)
echo.
echo This window will stay open so you can read the result.
pause
exit /b %RC%
