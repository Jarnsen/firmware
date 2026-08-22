@echo off
setlocal
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
    pause
    exit /b 2
  )
)

%PY% tracker_log_download.py %*
set "RC=%errorlevel%"
echo.
if not "%RC%"=="0" pause
exit /b %RC%
