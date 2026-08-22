HELTEC TRACKER V1.1 - DIAGNOSTIC LOG
====================================

The Tracker records a bounded persistent event log in internal flash when
Diagnostic Logging is enabled. The log is intended for autonomous park/sleep,
GNSS, position and Bluetooth tests without an open serial monitor.

WINDOWS DOWNLOAD
1. Connect the Tracker by USB-C after the autonomous test.
2. Double-click tracker_log_download.bat.
3. Leave the window open.
4. On the Tracker go to:
      Service page -> long press -> Diagnostic Log -> Export via USB
5. The downloader creates a file named similar to:
      tracker-log-2026-08-22_143000.txt

The serial port only needs to be open during the later download. During the
actual park/sleep test the PC/serial monitor should be disconnected/closed so
it cannot veto sleep.

MENU
Service -> Diagnostic Log contains:
- Logging: On/Off
- Status / size
- Export via USB
- Clear Log

LOG STORAGE
- Current log: max approx. 256 KiB
- Previous rotated log: max approx. 256 KiB
- Total retained history: approx. 512 KiB
- Oldest data is replaced automatically.

IMPORTANT
The log downloader uses Python 3 + pyserial. The .BAT file automatically tries
to install pyserial if it is missing.
