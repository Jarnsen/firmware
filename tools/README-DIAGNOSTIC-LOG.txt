DIAGNOSTIC LOG DOWNLOAD - TRACKER V1.1 / HELTEC V3
===================================================

These three files belong together:
  diagnostic_log_download.bat
  diagnostic_log_download.py
  README-DIAGNOSTIC-LOG.txt

Windows quick start
-------------------
1. Connect the device with USB-C.
2. Double-click diagnostic_log_download.bat.
3. On the device open:
      Service -> Diagnostic Log -> Export via USB
4. Keep the window open until both device and PC report completion.
5. The log is saved as diagnostic-log-YYYY-MM-DD_HHMMSS.txt.

The BAT file installs pyserial automatically if Python/pip are available.
The Python script can also be started directly, for example:
  python diagnostic_log_download.py --port COM7

Important
---------
- Do not use a serial monitor at the same time; only one program can own the COM port.
- The downloader does not clear the receive buffer when opening the port. This avoids losing the begin marker during the Windows/USB CDC open race.
- If USB disconnects during transfer, the firmware returns to WAIT_USB and restarts from byte zero after reconnection. A partial PC file is kept if the downloader itself loses the port.
- The shared downloader accepts the new JARNSEN diagnostic protocol and the older TRACKER_LOG / V3_LOG marker pairs, so older firmware can still be read.

Shared protocol used by new builds
----------------------------------
  ===JARNSEN_DIAG_LOG_BEGIN===
  # device=...
  # bytes=...
  <persistent diagnostic log>
  ===JARNSEN_DIAG_LOG_END===
