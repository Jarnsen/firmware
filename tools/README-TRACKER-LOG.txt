HELTEC TRACKER V1.1 – DIAGNOSTIC LOG DOWNLOAD
==============================================

Enthalten:
- tracker_log_download.bat
- TRACKER_V11_DIAG_LOG_DOWNLOADER.py

Ablauf unter Windows
--------------------
1. Tracker per USB-C verbinden.
2. tracker_log_download.bat doppelklicken.
3. Falls mehrere Ports angezeigt werden: Tracker-COM-Port auswählen und mit Enter bestätigen.
4. Der Downloader öffnet den Port und wartet. Der Tracker muss weiterhin vollständig bedienbar bleiben.
5. Am Tracker öffnen:
      Service -> Diagnostic Log -> Export via USB
6. HOLD: EXPORT NOW lang bestätigen.
7. Die Übertragung startet automatisch.
8. Nach DONE wird der COM-Port geschlossen. Das Log liegt unter Downloads\Meshtastic-Logs.

Wichtig
-------
- Es gibt nach der COM-Auswahl keinen zweiten PC-Enter-Schritt.
- Meshtastic Serial Console und andere COM-Port-Programme vorher schließen.
- Nur ein Programm darf den COM-Port gleichzeitig besitzen.
- GPIO0, kurze/lange Tastendrücke, Display und Servicemenü müssen auch bei
  geöffnetem Downloader funktionieren. Andernfalls den Build nicht freigeben.
- Nach Erfolg, Timeout oder USB-Fehler schließt der Downloader den Port.
- Ein zweiter Export muss ohne Neustart des Trackers funktionieren.
