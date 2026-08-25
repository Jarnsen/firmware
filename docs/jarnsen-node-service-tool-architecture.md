# Jarnsen Node Service Tool – gemeinsame Architektur

## Ziel

Es gibt genau **eine** Windows-App für alle unterstützten Jarnsen-Hardwarevarianten. Die App wird auf dem Branch `jarnsen-node-service-tool` gebaut und als `Jarnsen-Node-Service-Tool.exe` veröffentlicht.

Der Shared-Build wird automatisch in diese Releases kopiert:

- `jarnsen-service-tool-latest`
- `jarnsen-tracker-latest`
- `jarnsen-v3-latest`

Damit enthalten Tracker und V3 dieselbe EXE. Neue Hardware wird später nur als weiteres Profil ergänzt.

## Hardwareprofile

Die App verwendet `HARDWARE_PROFILES`. Ein Profil beschreibt mindestens:

- Anzeigename
- interne Gerätekennung (`device`)
- Firmware-Release
- OTA-Manifest / Updateabbild

Aktuell:

- `TRACKER` → Tracker V1.1 / `HELTEC_TRACKER_V1.1`
- `V3` → Heltec V3 / `HELTEC_V3_REPEATER`

## Einheitlicher Power-Vertrag

Das Tool wertet Power-Daten hardwareunabhängig aus. Eine Firmware darf intern INA226, einen anderen Stromsensor oder eine interne Power-Quelle verwenden. Für das Tool zählen die normalisierten Werte aus BATTERY/BATTERY_LEARN:

- Spannung und Ladezustand
- aktuelle Stromaufnahme
- kumulierter Verbrauch in mAh
- gelernte nutzbare Kapazität
- Restkapazität
- Vertrauen und Lernzyklen
- Laufzeitzähler (Bewegung/Park bzw. Listen/Service, GPS, BLE, Display, Light/Deep Sleep)
- TX-Zähler

Durchschnittsverbrauch wird **nicht** aus einzelnen Strom-Samples gebildet, sondern aus der Differenz kumulierter mAh zwischen zwei Logzeitpunkten. Dadurch bleiben 24-h-/7-Tage-Werte stabil und belastbar.

Die bestehende Tracker- und V3-Firmware besitzt bereits Kapazitätslernen: Ein ausreichend großer Entladebereich wird mit dem über den INA226 integrierten Verbrauch kombiniert; Kapazität, Vertrauen und Lernzyklen werden persistent gespeichert.

## Serieller GitHub-Updater

Der Shared-Build enthält `esptool` direkt in der EXE. Für Tracker V1.1 und V3 gilt der sichere Bootstrap:

- Hauptfirmware (`*.update.bin`) → `0x10000`
- `otaBTupdate.bin` → `0x340000`
- OTA-Bootauswahl zurücksetzen → Bereich `0xE000`, Länge `0x2000` löschen

Firmware und OTA-Loader werden aus dem passenden GitHub-Release geladen und vor dem Flashen per SHA-256 gegen das Manifest geprüft. Ein Windows-„Seriell über Bluetooth“-Port wird als Flash-Port abgelehnt.

Der normale USB-Updater löscht weder NVS noch Meshtastic-Einstellungen noch Diagnose-Logs.

## OTA-Recovery

Wenn ein wartender OTA-Loader den Gerätetyp nicht eindeutig meldet, zeigt die App keine Ja/Nein-Frage mehr. Stattdessen gibt es drei eindeutige Aktionen:

- **Heltec V3**
- **Tracker V1.1**
- **Abbrechen**

## Neue Hardware hinzufügen

Für eine weitere Hardwarevariante sind im Normalfall nur folgende Punkte nötig:

1. neues `HARDWARE_PROFILES`-Profil,
2. Release-Tag und OTA-Manifest,
3. Gerätekennung im Diagnose-Header,
4. kompatible Power-Metriken,
5. optional eigener Flashplan, falls die Offsets von ESP32-S3/otaBTupdate abweichen,
6. Shared-App-Workflow um den neuen Firmware-Release als zusätzliches Verteilziel ergänzen.

Die GUI, Historie, Trends, BLE-Logdownload, Power-Analyse und gemeinsame App-Version bleiben unverändert.