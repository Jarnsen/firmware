# Heltec Wireless Tracker V1.1 - GPIO0 Service- und Einstellmenü

Dieses Menü gilt für beide Rollen der Tracker-V1.1-Spezialfirmware:

- `TAK_TRACKER` - autonomer Kfz-Tracker mit Park-Deep-Sleep.
- `TAK` - Führungselement mit LoRa/GNSS und Light Sleep.

## Bluetooth-Verhalten

Bluetooth muss in der **gespeicherten Meshtastic-Konfiguration grundsätzlich aktiviert** bleiben, damit der ESP32 die BLE-Ressourcen beim Booten nicht freigibt. Die Spezialfirmware hält Bluetooth im normalen Betrieb trotzdem ausgeschaltet.

**Bluetooth wird bei beiden Rollen nur durch einen bewussten Druck auf den onboard GPIO0/USER-Taster eingeschaltet.** Bewegung am SW-18010P schaltet Bluetooth nicht ein.

Ein Tastendruck öffnet zunächst ein Servicefenster mit **120 Sekunden Leerlaufzeit**. Solange ein Meshtastic-/ATAK-Telefon tatsächlich per BLE verbunden ist, wird diese Leerlaufzeit automatisch weitergeschoben. Dadurch bricht eine laufende Service- oder ATAK-Sitzung nicht nach exakt zwei Minuten ab. Als Schutz gegen versehentlichen Dauerbetrieb gilt zusätzlich eine **harte Obergrenze von 15 Minuten** pro Servicefenster.

Beim `TAK_TRACKER` wird während des Servicefensters die autonome Power-Saving-/Deep-Sleep-Logik vorübergehend ausgesetzt, damit das Gerät nicht mitten in einer Einstellsitzung einschläft. Danach wird der normale Parkbetrieb wiederhergestellt.

## Bedienung mit nur einer Taste

1. **Erster Tastendruck:** Bluetooth + Servicefenster öffnen; Statusseite anzeigen.
2. **Kurzer Tastendruck:** zur nächsten Menüseite wechseln.
3. **Langer Tastendruck (ca. 1,2 s):** Wert der aktuellen Einstellseite ändern.
4. Ohne BLE-Verbindung nach 120 s: Bluetooth und Display aus, normaler Betriebsmodus weiter.
5. Bei aktiver BLE-Verbindung: Servicefenster automatisch verlängert, maximal 15 min.

Ein langer Druck auf STATUS, DIAG oder VERSION ändert nichts. Damit kann das Menü nicht bereits beim Öffnen versehentlich verstellt werden.

## Menüseiten und Werte

### STATUS

Zeigt Rolle/Servicezustand, Akku, GNSS-Status und Bluetooth-Service an.

### DIAG

Zusätzliche Felddiagnose ohne Telefon:

- GNSS FIX/WAIT.
- Alter der letzten frischen Position.
- gelernte GNSS-TTFF beim `TAK_TRACKER`.
- Alter des autonomen Heartbeats beim `TAK`.
- Zustand des SW-18010P: `OK` oder `CHECK`.
- beim `TAK_TRACKER` Anzahl erkannter Bewegungen ohne vorherigen GPIO7-Wake.

`CHECK` wird unter anderem gesetzt, wenn GPIO7 länger als 30 s LOW bleibt oder der Tracker bei einem späteren Timer-Fix mindestens 200 m von der gespeicherten Parkposition entfernt steht, ohne dass zuvor ein Motion-Wake erkannt wurde. Ein echter GPIO7-Motion-Wake bestätigt die Sensorleitung wieder.

### VERSION

Zeigt die Projektversion `JARN-MESH 1.1`, die ersten acht Zeichen des Git-Commit-SHA, Uptime und Wake-Grund. Der Hardware-Workflow erzeugt den Build-SHA automatisch unmittelbar vor dem Kompilieren.

### MOTION - Empfindlichkeit SW-18010P

| Stufe | Bestätigung | Verwendung |
| --- | ---: | --- |
| `VERY SENS` | 2 Pulse innerhalb 3 s | sehr empfindlich |
| `SENSITIVE` | 3 Pulse innerhalb 4 s | empfindlicher als Standard |
| `NORMAL` | **3 Pulse innerhalb 3 s** | **Standard** |
| `ROBUST` | 4 Pulse innerhalb 3 s | weniger Fehltrigger |

Die Einstellung wird von `TAK` und `TAK_TRACKER` direkt für die Bewegungserkennung verwendet.

### MIN DISTANCE - Mindeststrecke

Auswahl: **50 / 75 / 100 / 150 m**. Standard: **75 m**.

### MIN INTERVAL - Mindestzeit

Auswahl: **30 / 45 / 60 / 90 s**. Standard: **30 s**.

Die Smart-Position-Zeit wird nach einer Änderung sofort im laufenden `PositionModule` aktualisiert; ein Neustart ist nicht erforderlich.

### PARK UPDATE / HEARTBEAT

Auswahl: **30 / 60 / 120 / 240 min**. Standard: **60 min**.

- `TAK_TRACKER`: Intervall zwischen den geparkten Timer-Wakes.
- `TAK`: autonomes Positions-Heartbeat-Intervall im stationären Führungsbetrieb.

Für Intervalle ab einer Stunde wird pro Node dauerhaft ein kleiner, aus der Node-ID abgeleiteter Versatz abgezogen. Bei der 60-Minuten-Einstellung liegt das effektive Intervall dadurch zwischen **57 und 60 Minuten**. So senden viele gemeinsam gestartete Tracker später nicht immer gleichzeitig. Der 30-Minuten-Preset bleibt unverändert.

## Adaptive GNSS-TTFF

Der `TAK_TRACKER` misst bei geparkten Timer-Wakes die tatsächliche Zeit bis zum ersten frischen GNSS-Fix und bildet daraus einen geglätteten Lernwert. Bei erfolgreichen Zyklen wird das nächste GNSS-Wartefenster auf **gelernte TTFF + 5 s Sicherheitsreserve** gesetzt und innerhalb **12 bis 45 s** begrenzt.

Nach fehlgeschlagenen Fix-Zyklen wird vorübergehend wieder das großzügige 45-s-Fenster verwendet. Bei mehreren aufeinanderfolgenden Fehlschlägen greift weiterhin der stromsparende Kurzzyklus mit regelmäßigen vollständigen Wiederholungsversuchen. Bei niedrigem Akku wird der gelernte Wert mit kleinerer Reserve innerhalb eines begrenzten Low-Battery-Fensters verwendet.

## Speicherung

Die vier Spezialwerte werden in einem eigenen ESP32-NVS-Namensraum (`trkV11`) gespeichert. Sie bleiben über Deep Sleep, Neustart und normales Aus-/Einschalten erhalten. Gelernte TTFF- und Diagnosewerte werden für die Schlafzyklen im RTC-Speicher gehalten.

Für die vier einstellbaren Werte ist das **lokale GPIO0-Menü die maßgebliche Einstellung**. Normale Meshtastic-Einstellungen wie Kanal, PSK, LoRa-Region, Namen oder TAK-Konfiguration können weiterhin während des Bluetooth-Servicefensters in der Meshtastic-App geändert werden.

## Standardwerte

Nach frischer Installation bzw. ohne vorhandene NVS-Werte:

- Motion: `NORMAL` = 3 Pulse / 3 s
- Mindeststrecke: 75 m
- Mindestintervall: 30 s
- Park-/Heartbeat-Intervall: 60 min, effektiv 57-60 min pro Node
- Bluetooth-Service: 120 s Leerlauf, automatische Verlängerung bei BLE-Verbindung, maximal 15 min
