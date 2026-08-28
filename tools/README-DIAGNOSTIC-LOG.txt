HELTEC V3 – DIAGNOSTIC LOG DOWNLOAD
=====================================

Enthalten:
- V3_Diagnostic_Log_Download.bat
- V3_DIAG_LOG_DOWNLOADER.py

Ablauf unter Windows
--------------------
1. V3 per USB-C verbinden.
2. V3_Diagnostic_Log_Download.bat doppelklicken.
3. Falls mehrere Ports angezeigt werden: V3-COM-Port auswählen und mit Enter bestätigen.
4. Der Downloader öffnet den Port und wartet. Der V3 muss weiterhin vollständig bedienbar bleiben.
5. Am V3 öffnen:
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
- Ein zweiter Export muss ohne Neustart des V3 funktionieren.
