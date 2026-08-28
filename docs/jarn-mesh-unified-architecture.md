# JARN-MESH Unified Core – Phase 0 Baseline

## Ziel

Die bestehende JARN-MESH-Architektur wird kontrolliert auf einen gemeinsamen Core mit mehreren Hardware-Adaptern und rollenbasiertem Verhalten umgestellt.

Langfristiges Ziel:

- ein gemeinsamer JARN-MESH Core,
- ein eigener Build pro Hardware,
- keine eigene Firmwarelinie nur wegen einer Rolle,
- ein gemeinsames Jarnsen Node Service Tool,
- Hardware bestimmt Board-Capabilities,
- optionale Peripherie erweitert Capabilities,
- EffectiveCapabilities bestimmen, welche Rollen technisch zulässig sind,
- die Rolle bestimmt das Betriebsverhalten.

## Integrationsbranch

`refactor/jarn-mesh-unified-core`

Der Integrationsbranch basiert initial auf dem Tracker-V1.1-Branch `heltec-tracker-v11-vehicle-motion-wake`.

Begründung: Der Tracker-Zweig enthält die umfangreichste gemeinsame Service-/Diagnose-/OTA-/BLE-/WLAN-/Display-Basis und ist der am weitesten entwickelte der drei Firmwarezweige. Die Drone- und V3-spezifischen Funktionen werden gezielt übernommen und nicht als vollständige Branch-Merges eingespielt.

Die bestehenden Produktbranches bleiben während der Migration erhalten und werden nicht ersetzt:

- `heltec-tracker-v11-vehicle-motion-wake`
- `heltec-v3-repeater-light-sleep`
- `heltec-tracker-v11-drone-repeater`
- `jarnsen-node-service-tool`

## Referenzstände

### Tracker V1.1

- Produktversion: `JARN-MESH v1.9.1`
- Branch: `heltec-tracker-v11-vehicle-motion-wake`
- Phase-0-Branch-Head: `d1a9cf16c55d61c83927b7904ab48a42b5c8caf0`
- gegenüber `develop`: 430 Commits voraus

### Heltec V3 Repeater

- Produktversion: `JARN-MESH V3 Repeater v1.7.1`
- Branch: `heltec-v3-repeater-light-sleep`
- Phase-0-Branch-Head: `4bf16cefca4ca7471a3507c6786c19ef14ae9937`
- gegenüber `develop`: 313 Commits voraus

### Drone Repeater

- Produktversion: `JARN-DRONE Repeater v1.5.1`
- Branch: `heltec-tracker-v11-drone-repeater`
- Phase-0-Branch-Head: `8907b329439ed6851b3b0181660d9ea7b6da0d58`
- gegenüber dem aktuellen Tracker-Zweig stark zurückliegend, besitzt aber ca. 50 eigene Commits seit dem gemeinsamen Tracker-Merge-Base

### Jarnsen Node Service Tool

- Branch: `jarnsen-node-service-tool`
- Phase-0-Branch-Head: `5df8560d49389e493b9af1697ebb01388beaa711`
- aktueller Workflow-Manifeststand: `2.1.25`
- eigene unabhängige Versionslinie
- darf niemals an eine Firmwareversion gekoppelt werden

## Zielmodell

```text
JARN-MESH Unified Core
│
├── Core
│   ├── BLE / Service Transport
│   ├── WLAN / Captive Portal
│   ├── OTA / Update
│   ├── Logging / Diagnostics Framework
│   ├── Live Display
│   ├── Position History / MGRS helpers
│   ├── gemeinsame Mesh-/TAK-Helfer
│   └── Firmware-/Node-Metadaten
│
├── Hardware Layer
│   ├── Heltec Tracker V1.1
│   ├── Heltec V3
│   ├── zukünftig Heltec V4
│   ├── zukünftig Seeed / weitere Boards
│   └── weitere Hardware
│
├── Peripheral Layer
│   ├── internes GPS
│   ├── externes GPS
│   ├── INA226
│   ├── Bewegungssensoren
│   └── weitere optionale Sensoren
│
├── Effective Capabilities
│
└── Roles
    ├── TAK_TRACKER
    ├── TAK_REPEATER
    └── DRONE_REPEATER
```

## Capability-Modell

Capabilities dürfen nicht nur aus dem Boardtyp abgeleitet werden.

Es werden drei Ebenen unterschieden:

1. **BoardCapabilities** – fest integrierte bzw. grundsätzlich verfügbare Hardwareeigenschaften.
2. **PeripheralCapabilities** – tatsächlich angeschlossene oder persistent konfigurierte optionale Peripherie.
3. **EffectiveCapabilities** – das für Rollen und Features relevante Gesamtergebnis.

Beispiel Heltec V3:

```text
BoardCapabilities:
internalGps = false
supportsExternalGps = true

PeripheralCapabilities:
externalGps = true

EffectiveCapabilities:
gps = true
```

Ein V3 mit externem GPS darf damit später GPS-abhängige Rollen erhalten, sofern alle übrigen Voraussetzungen erfüllt sind. Dafür darf kein eigener V3-GPS-Build notwendig sein.

## Rollenprinzip

Hardware bestimmt, was technisch möglich ist.

Peripherie erweitert die technischen Möglichkeiten.

Die Rolle bestimmt, wie sich die Node verhält.

```text
Tracker V1.1 + DRONE_REPEATER
=> Drone-Repeater-Verhalten

Tracker V1.1 + TAK_TRACKER
=> Fahrzeug-/Tracker-Verhalten

V3 ohne GPS + TAK_REPEATER
=> Repeater-Verhalten

V3 + externes GPS + TAK_TRACKER
=> später möglich, wenn die vollständige Capability-Matrix erfüllt ist
```

## Phase-0-Funktionsmatrix

Legende:

- **JA** = Funktion ist im jeweiligen Referenzzweig nachweisbar vorhanden.
- **TEIL** = Funktion ist vorhanden, aber anders implementiert oder nicht in gleicher Tiefe.
- **NEIN/–** = nicht Bestandteil dieses Referenzzweigs bzw. nicht als eigener Funktionsblock nachweisbar.
- **PRÜFEN** = in Phase 5 gegen die reale Drone-Funktionsparität nochmals verbindlich prüfen.

| Funktion | Tracker V1.1 | V3 Repeater | Drone Repeater | Klassifizierung | Ziel im Unified Core |
|---|---|---|---|---|---|
| BLE-Grundtransport | JA | JA | JA | gemeinsam | Core Service Transport |
| BLE Service Mode | JA | JA | JA | gemeinsam + Rollenparameter | Core Service Session |
| Live Display / Fernbedienung | JA | JA | JA | gemeinsam | Core LiveDisplay |
| WLAN/AP | JA | JA | –/PRÜFEN | gemeinsam, sofern Board WLAN hat | Core WiFi Service |
| Captive Portal / Service Web | JA | JA | –/PRÜFEN | gemeinsam + Hardware-Metadaten | Core ServiceWeb |
| GitHub-OTA über WLAN | JA | JA | Workflow/Release vorhanden; Runtime prüfen | gemeinsam | Core OTA |
| Bluetooth/Service-OTA | JA | JA | JA | gemeinsam | Core OTA Transport |
| USB-Service / Log-Sync | JA | JA | TEIL | gemeinsam + Transportadapter | Core Service Transport |
| Firmware-/Build-Metadaten | JA | JA | JA | historisch dupliziert | Core BuildInfo + Build Generated |
| Diagnose-Logging | JA | JA | JA | historisch dupliziert | Core Diagnostic Framework + Adapter |
| Logdownload | JA | JA | JA | gemeinsam | Core Service API |
| Log Delta/Cursor/ACK | JA | JA | älterer Stand | gemeinsam | Core Service Protocol |
| Live-Diagnose | JA | JA | TEIL | gemeinsam | Core Diagnostic API |
| Positionshistorie | JA | JA | PRÜFEN | gemeinsam | Core Position History |
| Offline-Karte / Positions-Webansicht | JA | JA | –/PRÜFEN | gemeinsam | Core ServiceWeb |
| internes GPS | JA | NEIN | JA | Hardware/Peripheral | Tracker GPS Provider |
| externes GPS | zukünftig möglich | zukünftig vorgesehen | zukünftig möglich | Peripheral | External GPS Provider |
| Phone-GPS / Phone Position | TEIL | JA, umfangreich | –/PRÜFEN | Service/Peripheral-Quelle | Core Position Provider |
| Bewegungssensor / Motion Wake | JA | nicht integriert | Hardware könnte erweitert werden | Hardware/Peripheral | Motion Provider |
| TAK Tracker Bewegungsstrategie | JA | NEIN ohne GPS | NEIN | Rolle | TAK_TRACKER |
| TAK Repeater Verhalten | bestehende TAK-Logik | JA | Repeater-Grundverhalten | Rolle | TAK_REPEATER |
| Drone dynamische Positionsintervalle | NEIN | NEIN | JA | Rolle | DRONE_REPEATER |
| Drone Air-Utilization Brake | NEIN | NEIN | JA | Rolle | DRONE_REPEATER |
| Drone GPS Fix Recovery/Immediate TX | NEIN | NEIN | JA | Rolle | DRONE_REPEATER |
| Light Sleep | JA | JA | TEIL/PRÜFEN | Core Policy + Hardware Wake Adapter | Power Framework |
| Deep Sleep | JA, TAK_TRACKER | nicht Hauptprofil | –/PRÜFEN | Rolle + Hardware | Power Framework |
| Wake über Button | JA | JA | JA | Hardware + Core Event | Hardware Input Adapter |
| Wake über Motion | JA | NEIN | nicht genutzt | Peripheral | Motion Provider |
| BLE Wake/Service Öffnung | JA | JA | JA | gemeinsam | Core Service Session |
| USB-Power-Erkennung | JA | JA | JA | Hardware/Peripheral | Power Provider |
| Akku-/Power-Monitor | JA | JA | JA | Framework gemeinsam, Messung hardwareabhängig | Core Power + Hardware Adapter |
| INA226 | unterstützt/integrierbar | dokumentiert/integrierbar | nicht zentral | optionale Peripherie | INA226 Provider |
| Mesh Health | JA | JA | JA | gemeinsam + Rollenmetriken | Core Mesh Health |
| Antennentest | JA explizit | kein gleichwertiges eigenes Modul nachgewiesen | – | Feature + Hardware RF | Diagnostics Feature |
| Mesh Monitor/Test | JA | JA | JA/Health | gemeinsam | Core Mesh Diagnostics |
| Display-Grundsystem | JA | JA | JA | gemeinsam | Core Display Framework |
| Status-/Service-Seiten | JA | JA | JA | gemeinsam + Page Provider | Core Display + Rollen-Seiten |
| MGRS/Positionsdarstellung | JA | JA | PRÜFEN | gemeinsam | Core Position Formatting |
| Service Settings | JA | V3 eigener Service Stack | TEIL | gemeinsam + Capabilities | Core Service Settings |
| Firmwareprüfung | JA | JA | Paketierung vorhanden | gemeinsam | Core Update Service |
| Fleet-/Gruppenupdate | über Jarnsen Node Service Tool | über Jarnsen Node Service Tool | über Tool/Paketierung | Tool-Funktion | Jarnsen Node Service Tool |
| Hardwareerkennung im Tool | JA Tracker/V3 | JA Tracker/V3 | Tracker-Hardware | Tool-Funktion | Capability Descriptor API |
| Rollenwahl im Tool | bestehende Profile | bestehende Profile | separate Firmware | soll vereinheitlicht werden | Role API + Tool UI |

## Konkrete Duplikat-Inventur

### 1. Exaktes Duplikat: Live Display

`src/JarnsenLiveDisplay.cpp` ist im aktuellen Tracker- und V3-Zweig byte-identisch (gleicher Git-Blob). Dieses Modul ist ein klarer erster Core-Kandidat und soll nicht länger hardwareweise gepflegt werden.

Ziel:

```text
src/jarnsen/core/display/JarnsenLiveDisplay.*
```

### 2. Nahezu gemeinsames Modul: Position History

`src/mesh/http/JarnsenPositionTrack.cpp` existiert sowohl auf Tracker als auch V3 mit derselben Grundlogik. Der erkennbare Hardwareunterschied liegt insbesondere in der Wahl des jeweiligen Diagnostic-Loggers.

Ziel: Positionshistorie in den Core; Logging nur noch über eine gemeinsame Diagnostic-Schnittstelle statt direkter `TrackerDiagnosticLog`-/`HeltecV3DiagnosticLog`-Abhängigkeit.

### 3. Nahezu gemeinsames Modul: Service Web / Captive Portal

`src/mesh/http/JarnsenServiceWeb.cpp` ist bereits strukturell für Tracker und V3 gemeinsam angelegt, enthält aber weiterhin Board-Abfragen für:

- Diagnostic Logger,
- Device Code/Title,
- SSID,
- GitHub Release Tag,
- Firmware Asset,
- einzelne V3 Lifecycle-Callbacks.

Ziel: Webserver, HTML, OTA, Positionsseite und HTTP-Protokoll bleiben Core. Hardware-/Build-Metadaten kommen über `HardwareProfile`/`FirmwareDescriptor`; Lifecycle-Callbacks über ein Interface.

### 4. BLE/NimBLE

Tracker und V3 haben umfangreiche, separat weiterentwickelte Änderungen an `NimbleBluetooth.cpp`. Der überwiegende Service-/Live-/Tool-Transport ist fachlich gemeinsam; hardware- bzw. rollenbezogene Wake-/Ownership-Reaktionen dürfen nicht direkt im Bluetooth-Core verbleiben.

Ziel: gemeinsamer BLE-Service mit Events/Callbacks an FeatureManager und Hardware Input/Power Layer.

### 5. RadioLibInterface / Mesh-Hooks

Tracker und V3 verändern beide `RadioLibInterface.cpp`. Gemeinsame Jarnsen-Telemetrie und Mesh-Hooks gehören in einen gemeinsamen Hook/Observer. Hardware- oder rollenabhängige Reaktionen werden dahinter registriert.

### 6. PowerFSM

Tracker, V3 und Drone besitzen eigene beziehungsweise abweichende Power-Entscheidungen. Der Zustandsautomat und gemeinsame Begriffe sollen vereinheitlicht werden, aber GPIOs, USB-Erkennung, Wake-Quellen und konkrete Sleep-Fähigkeiten bleiben Hardware-/Peripheral-Adapter.

### 7. Diagnose

Aktuell existieren mindestens:

- `TrackerDiagnosticLog`,
- `HeltecV3DiagnosticLog`,
- `DroneDiagnosticLog`.

Sie erfüllen weitgehend dieselbe Querschnittsaufgabe, enthalten aber unterschiedliche Eventnamen und Quellen.

Ziel: ein `JarnsenDiagnostic`-Framework mit gemeinsamen Events/Metadaten; Hardware- und Rollenmodule liefern nur ihre spezifischen Messwerte/Eventdetails.

### 8. Power Monitor

Aktuell existieren:

- `TrackerPowerMonitor`,
- `HeltecV3PowerMonitor`,
- `DronePowerMonitor`.

Ziel: gemeinsame Power-Metriken und History im Core; Messquellen und Power Policy getrennt in Hardware/Peripheral beziehungsweise Rolle.

### 9. Status-/Displayseiten

Tracker, V3 und Drone besitzen jeweils eigene Statusseiten. Layout-, Navigation-, Version-/Build- und gemeinsame Metrikdarstellung sollen im Core liegen. Rollen- und Hardwareseiten werden über Page Provider registriert.

### 10. BuildInfo

Aktuell existieren getrennte `JarnsenBuildInfo`, `HeltecV3BuildInfo` und `DroneBuildInfo`.

Ziel: eine gemeinsame Firmwareversionsstruktur mit Hardware-ID, Build-SHA, Buildnummer und aktiver Rolle als getrennte Felder. Die Migration auf eine gemeinsame Produktversion erfolgt erst in Phase 9.

## Architekturprobleme, die beim Umbau explizit gelöst werden müssen

### Tracker: Rolle und Hardware sind aktuell vermischt

`TrackerVariantPolicy` aktiviert die gemeinsame Tracker-Policy anhand von Meshtastic-Rollen TAK/TAK_TRACKER. `TrackerCommonPolicy` enthält gleichzeitig Motion-Hardware, GPS, Service, BLE, Display, Sleep und Positionsstrategie.

Diese Verantwortlichkeiten müssen getrennt werden in:

- Hardware Input/Motion Provider,
- GPS Provider,
- Service Session,
- Power Framework,
- TAK_TRACKER / TAK_REPEATER Role Policy.

### V3: Monolithische Repeater Policy

`HeltecV3RepeaterPolicy` enthält derzeit unter anderem:

- Repeater-Rollenprüfung,
- BLE Service Lifecycle,
- Button Ownership,
- USB Maintenance,
- Displayseiten,
- Phone Position Handling,
- Wake-Zähler,
- Power/Sleep-Entscheidungen.

Diese Datei darf nicht einfach zum neuen Core werden. Sie wird später in gemeinsame Services, V3-Hardwareadapter, Position Provider und `TAK_REPEATER`-Rollenlogik zerlegt.

### Drone: Compile-Time-Rolle

Die Drone Policy wird aktuell über `JARNSEN_DRONE_REPEATER_BUILD` kompiliert und ist damit als separate Firmwarevariante realisiert. Gleichzeitig nutzt sie dieselbe Tracker-V1.1-Hardware und internes GPS.

Einzigartige Drone-Funktionen, die verbindlich erhalten werden müssen:

- dynamische Positionsintervalle abhängig von Geschwindigkeit,
- Channel-/Air-Utilization Brake,
- unmittelbare Positionsmeldung nach GPS-Fix/Recovery,
- Drone-spezifische Power Policy,
- Drone System Health,
- Drone Mesh Health/Metriken,
- Drone Status Pages und Service-Verhalten.

In Phase 5 werden diese Funktionen als Runtime-Rolle `DRONE_REPEATER` migriert. Die bisherige Drone-Firmware bleibt bis zur vollständigen Funktionsparität erhalten.

## Verbindliche Übernahmeliste aus dem V3-Zweig

Nicht den ganzen V3-Branch mergen. Gezielt analysieren beziehungsweise übernehmen:

1. `HeltecV3RepeaterPolicy` – nur nach Verantwortlichkeiten zerlegt.
2. `HeltecV3PowerMonitor` – Messlogik/Erfahrungen in Power Framework + V3 Adapter.
3. `HeltecV3DiagnosticLog` – Event-/Metrikparität in gemeinsames Diagnostic Framework.
4. `HeltecV3MeshMonitor` und `HeltecV3MeshPages` – gemeinsame Mesh Diagnostics, V3-spezifische Teile über Adapter.
5. `HeltecV3PhonePositionManager` / `Estimate` – Position Provider statt V3-Sonderlogik.
6. `HeltecV3PositionPage` – gemeinsame Position Page + Provider.
7. `HeltecV3ServicePage` / `ServiceWebStart` – gemeinsame Service Session, V3 Hooks separat.
8. V3 Button-/Wake-/Light-Sleep-Verhalten – ausschließlich im V3 Hardware Layer.
9. V3 Phone-Internet-/Remote-WLAN-Erfahrungen – in gemeinsamen Service Stack, soweit hardwareunabhängig.
10. V3 BuildInfo – nur Metadatenmodell übernehmen, nicht separate Versionsarchitektur fortführen.

## Verbindliche Übernahmeliste aus dem Drone-Zweig

Nicht den Drone-Branch mergen. Gezielt migrieren:

1. `HeltecTrackerV11DroneRepeaterPolicy` → `DRONE_REPEATER` Role Policy.
2. `DroneDiagnosticLog` → gemeinsame Diagnoseevents + Drone Role Events.
3. `DronePowerMonitor` → Power Framework + Drone Role Policy.
4. `DroneMeshHealth` → gemeinsames Mesh Health mit Drone-Metriken.
5. `DroneSystemHealth` → Role Health Provider.
6. `DroneStatusPages` → Role Page Provider.
7. GPS-/Positionstaktung inklusive Speed-/Air-Utilization-Regeln.
8. Service-/BLE-Verhalten mit aktuellem gemeinsamen Service Stack abgleichen.
9. OTA-/Packaging-Funktionen nur dort übernehmen, wo sie gegenüber dem aktuellen Tracker-Workflow noch relevant sind.
10. Alle Punkte in Phase 5 gegen die alte Drone-Firmware als Referenz testen.

## Jarnsen Node Service Tool

Es bleibt genau ein Service Tool: **Jarnsen Node Service Tool**.

Der aktuelle Tool-Workflow erzeugt bereits ein gemeinsames Manifest mit:

- `app = Jarnsen Node Service Tool`,
- `version = 2.1.25`,
- Shared Channel,
- Unterstützung für Tracker V1.1 und V3 Repeater.

Die bestehende Versionsautomatik des Tools bleibt unabhängig.

Das Tool soll langfristig von jeder Node strukturiert auslesen können:

- Board / Hardware,
- Firmwareversion,
- aktive Rolle,
- BoardCapabilities,
- erkannte / konfigurierte Peripherie,
- EffectiveCapabilities,
- Stromversorgungsstatus,
- unterstützte Rollen,
- aktuelle Hardware-/Peripheral-Fehler.

Diese Informationen werden später in die Nodeübersicht integriert.

Für zukünftige Hardware (Heltec V4, Seeed usw.) darf das Tool nicht mit festen `if board == ...`-UI-Sonderfällen wachsen. Primär sollen Firmware-Descriptor und Capability-Descriptor die Darstellung treiben.

## Phase-1-Zielstruktur

Die konkreten Ordnernamen dürfen sich an Meshtastic-Konventionen anpassen, die Verantwortlichkeiten sind jedoch verbindlich:

```text
src/jarnsen/
├── core/
│   ├── capabilities/
│   ├── diagnostics/
│   ├── display/
│   ├── service/
│   ├── position/
│   ├── power/
│   └── update/
├── hardware/
│   ├── tracker_v11/
│   └── heltec_v3/
├── peripherals/
│   ├── gps/
│   ├── motion/
│   └── ina226/
└── roles/
    ├── tak_tracker/
    ├── tak_repeater/
    └── drone_repeater/
```

## Sicherheits- und Migrationsregeln

1. Kein bestehender Tracker-, V3- oder Drone-Produktbranch wird während des Umbaus gelöscht.
2. Phase 0 verändert keinen funktionalen Firmwarecode.
3. Keine alte Implementierung wird entfernt, bevor die neue Implementierung für die betroffenen Hardware-Builds kompiliert und getestet wurde.
4. Keine vollständigen V3-/Drone-Branch-Merges in den Unified-Core-Branch.
5. Gemeinsame Module zuerst extrahieren, Hardware- und Rollenlogik erst danach entkoppeln.
6. Hardware-Capabilities und Rollen dürfen nicht gegenseitig fest verdrahtet werden.
7. Optionale Peripherie muss später ohne eigenen Firmware-Fork möglich sein.
8. Der Jarnsen Node Service Tool Branch bleibt separat und behält seine eigene Version.
9. Versionsnummern der bisherigen Firmwarelinien bleiben bis zur Phase 9 Referenzwerte.
10. Die Drone-Firmware wird erst nach nachgewiesener `DRONE_REPEATER`-Parität deprecated/archiviert.

## Phasen

0. Bestandsaufnahme und Sicherheitsnetz
1. Architekturgrundlage
2. gemeinsamen Core extrahieren
3. Hardware-Abstraction-Layer
4. Rollen- und Capability-System
5. Drone Repeater als Rolle migrieren
6. Jarnsen Node Service Tool anbinden
7. Workflows vereinfachen
8. Funktionsparität und Bereinigung
9. gemeinsame Versionsstrategie / produktiver Merge

## Phase-0-Abschluss

- Integrationsbranch: **erstellt**
- Basis: **Tracker V1.1**
- Tracker-, V3- und Drone-Produktbranches: **bleiben unangetastet**
- Service-Tool-Produktbranch: **bleibt separat und unangetastet**
- Funktionsmatrix: **erstellt**
- Duplikat-Inventur: **erstellt**
- V3-Übernahmeliste: **erstellt**
- Drone-Übernahmeliste: **erstellt**
- Capability-/Peripheral-Modell: **festgelegt**
- zukünftige Hardwareerweiterbarkeit: **verbindlich berücksichtigt**
- funktionaler Firmwarecode in Phase 0 geändert: **NEIN**
- Phase 1 darf beginnen: **JA**
