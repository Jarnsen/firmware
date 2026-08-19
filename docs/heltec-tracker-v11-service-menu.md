# Heltec Wireless Tracker V1.1 – GPIO0 Service- und Einstellmenü

Dieses Menü gilt für beide Rollen der Tracker-V1.1-Spezialfirmware:

- `TAK_TRACKER` – autonomer Kfz-Tracker mit Park-Deep-Sleep.
- `TAK` – Führungselement mit LoRa/GNSS und Light Sleep.

## Bluetooth-Verhalten

Bluetooth muss in der **gespeicherten Meshtastic-Konfiguration grundsätzlich aktiviert** bleiben, damit der ESP32 die BLE-Ressourcen beim Booten nicht freigibt. Die Spezialfirmware hält Bluetooth im normalen Betrieb trotzdem ausgeschaltet.

**Bluetooth wird bei beiden Rollen nur durch einen bewussten Druck auf den onboard GPIO0/USER-Taster eingeschaltet.** Bewegung am SW-18010P schaltet Bluetooth nicht ein.

Ein Tastendruck öffnet ein Servicefenster von **120 Sekunden**. Während dieser Zeit kann sich die Meshtastic-App bzw. bei `TAK` das ATAK/Meshtastic-Setup per Bluetooth verbinden. Nach Ablauf des Fensters wird Bluetooth wieder ausdrücklich ausgeschaltet.

Beim `TAK_TRACKER` wird während des Servicefensters die autonome Power-Saving-/Deep-Sleep-Logik vorübergehend ausgesetzt, damit das Gerät nicht mitten in einer Einstellsitzung einschläft. Danach wird der normale Parkbetrieb wiederhergestellt.

## Bedienung mit nur einer Taste

1. **Erster Tastendruck:** Bluetooth + Servicefenster öffnen; Statusseite anzeigen.
2. **Kurzer Tastendruck:** zur nächsten Menüseite wechseln.
3. **Langer Tastendruck (ca. 1,2 s):** Wert der aktuellen Einstellseite ändern.
4. Nach 120 s: Bluetooth aus, Display aus, normaler Betriebsmodus weiter.

Ein langer Druck auf der Statusseite ändert nichts. Damit kann das Menü nicht bereits beim Öffnen versehentlich verstellt werden.

## Menüseiten und Werte

### STATUS

Zeigt Rolle/Servicezustand, Akku, GNSS-Status und Bluetooth-Service an.

### MOTION – Empfindlichkeit SW-18010P

| Stufe | Bestätigung | Verwendung |
|---|---:|---|
| `VERY SENS` | 2 Pulse innerhalb 3 s | sehr empfindlich |
| `SENSITIVE` | 3 Pulse innerhalb 4 s | empfindlicher als Standard |
| `NORMAL` | **3 Pulse innerhalb 3 s** | **Standard** |
| `ROBUST` | 4 Pulse innerhalb 3 s | weniger Fehltrigger |

Die Einstellung wird von `TAK` und `TAK_TRACKER` direkt für die Bewegungserkennung verwendet.

### MIN DISTANCE – Mindeststrecke

Auswahl: **50 / 75 / 100 / 150 m**. Standard: **75 m**.

### MIN INTERVAL – Mindestzeit

Auswahl: **30 / 45 / 60 / 90 s**. Standard: **30 s**.

Die Smart-Position-Zeit wird nach einer Änderung sofort im laufenden `PositionModule` aktualisiert; ein Neustart ist nicht erforderlich.

### PARK UPDATE / HEARTBEAT

Auswahl: **30 / 60 / 120 / 240 min**. Standard: **60 min**.

- `TAK_TRACKER`: Intervall zwischen den geparkten Timer-Wakes.
- `TAK`: autonomes Positions-Heartbeat-Intervall im stationären Führungsbetrieb.

## Speicherung

Die vier Spezialwerte werden in einem eigenen ESP32-NVS-Namensraum (`trkV11`) gespeichert. Sie bleiben über Deep Sleep, Neustart und normales Aus-/Einschalten erhalten.

Für diese vier Werte ist das **lokale GPIO0-Menü die maßgebliche Einstellung**. Normale Meshtastic-Einstellungen wie Kanal, PSK, LoRa-Region, Namen oder TAK-Konfiguration können weiterhin während des Bluetooth-Servicefensters in der Meshtastic-App geändert werden.

## Standardwerte

Nach frischer Installation bzw. ohne vorhandene NVS-Werte:

- Motion: `NORMAL` = 3 Pulse / 3 s
- Mindeststrecke: 75 m
- Mindestintervall: 30 s
- Park-/Heartbeat-Intervall: 60 min
- Bluetooth-Servicefenster: 120 s
