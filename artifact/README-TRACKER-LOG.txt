HELTEC TRACKER V1.1 - DIAGNOSTIC LOG
====================================

The Tracker records a bounded persistent event log in internal flash when
Diagnostic Logging is enabled. The log is intended for autonomous park/sleep,
GNSS, position, INA226/power and Bluetooth tests without an open serial monitor.

DOWNLOADER IN THIS ARTIFACT
There is exactly one Tracker downloader:

  TRACKER_V11_DIAG_LOG_DOWNLOADER.py

Do not use the V3 downloader with this device.

WINDOWS DOWNLOAD
1. Close the Meshtastic Serial Console/Monitor and every other program that has
   the Tracker COM port open. A serial port cannot normally be shared.
2. Connect the Tracker by USB-C.
3. Start TRACKER_V11_DIAG_LOG_DOWNLOADER.py.
   - If .py files are associated with Python, double-click it.
   - Otherwise open a terminal in this folder and run:
       py TRACKER_V11_DIAG_LOG_DOWNLOADER.py
4. The downloader opens the COM port FIRST and reports that USB-Serial is ready.
5. On the Tracker go to:
      Service -> Diagnostic Log -> Export via USB
6. On the separate confirmation page move to:
      HOLD: EXPORT NOW
   and LONG press to confirm.
7. Keep the downloader open until it prints DONE.
8. It creates a file named similar to:
      TRACKER_V11_Diagnostic_Log_2026-08-23_210000.txt

The downloader automatically tries to install Python package pyserial if it is
missing. During the autonomous park/sleep test the PC/serial monitor should be
disconnected/closed so it cannot veto sleep.

MENU
Service -> Diagnostic Log contains the log controls. Export does NOT start just
by opening/selecting Export via USB; the second HOLD: EXPORT NOW confirmation is
required deliberately.

DISPLAY DURING SERVICE MENUS
While a Service/Diagnostic/Power selection menu is open, the display is kept on.
The normal display timeout resumes after leaving the menu. The overall service
idle timeout and hard safety cap still remain active.

LOG STORAGE
- Current log: bounded persistent flash log
- Old data rotates/replaces automatically according to the firmware log policy
- Export includes firmware version, build SHA, role and log-format metadata
