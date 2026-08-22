TRACKER DIAGNOSTIC LOG DOWNLOAD
===============================

Windows - recommended sequence
------------------------------
1. Connect the Heltec Tracker V1.1 with USB-C.
2. Double-click tracker_log_download.bat.
3. Wait until the PC window says READY.
4. On the Tracker open:
      Service -> Diagnostic Log -> Export via USB
5. The Tracker display should show:
      PC/Downloader verbinden
      PC erkannt - warte
      Uebertrage Log...
      Uebertragung fertig
   and a progress percentage while sending.
6. The PC window stays open after the transfer. On success it shows DONE and
   the full filename of tracker-log-YYYY-MM-DD_HHMMSS.txt.
7. Send that TXT file for analysis.

Important
---------
- Start the BAT/downloader BEFORE selecting Export via USB whenever possible.
- Do not close the PC window while the Tracker says Uebertrage Log....
- If USB disconnects during transfer, the Tracker returns to waiting state and
  restarts the log from byte zero after a stable reconnect.
- Normal power/sleep tests should be performed with the serial monitor closed;
  an actively opened native USB serial connection intentionally keeps the
  Tracker awake for maintenance.
