# JARN-MESH Unified Core – Phase 0 Baseline

## Ziel

Die bestehende JARN-MESH-Architektur wird kontrolliert auf einen gemeinsamen Core mit mehreren Hardware-Adaptern und rollenbasiertem Verhalten umgestellt.

Langfristiges Ziel:

- ein gemeinsamer JARN-MESH Core,
- ein eigener Build pro Hardware,
- keine eigene Firmwarelinie nur wegen einer Rolle,
- ein gemeinsames Jarnsen Node Service Tool,
- Hardware bestimmt Capabilities,
- optionale Peripherie erweitert Capabilities,
- Rolle bestimmt Verhalten.

## Integrationsbranch

`refactor/jarn-mesh-unified-core`

Der Integrationsbranch basiert initial auf dem aktuellen Tracker-V1.1-Branch `heltec-tracker-v11-vehicle-motion-wake`.

Begründung: Dieser Branch enthält aktuell die umfangreichste gemeinsame Service-/Diagnose-/OTA-/BLE-/WLAN-/Display-Basis und liegt deutlich weiter vor `develop` als die anderen Hardwarezweige. Die Drone- und V3-spezifischen Funktionen werden später gezielt übernommen und nicht als vollständige Branch-Merges eingespielt.

## Referenzstände

- Tracker V1.1: `JARN-MESH v1.9.1`
- Heltec V3 Repeater: `JARN-MESH V3 Repeater v1.7.1`
- Drone Repeater: `JARN-DRONE Repeater v1.5.1`
- Jarnsen Node Service Tool: eigene unabhängige Versionslinie; aktueller Tool-Branch enthält bereits v2.1.25-Arbeit. Die Tool-Version wird niemals an eine Firmwareversion gekoppelt.

## Aktuelle Branch-Situation

### Tracker V1.1

Branch: `heltec-tracker-v11-vehicle-motion-wake`

Der Branch liegt 430 Commits vor `develop` und enthält unter anderem:

- Tracker-spezifische GPS-/Motion-Logik,
- umfangreiche Diagnose und Logging,
- Power Monitoring,
- Service Web / Captive Portal,
- BLE / Live Display / OTA-Funktionen,
- Mesh Health / Antennentest,
- Service Settings / Upgrade,
- gemeinsame Jarnsen Service Tool Integration.

### Heltec V3 Repeater

Branch: `heltec-v3-repeater-light-sleep`

Der Branch liegt 313 Commits vor `develop` und enthält unter anderem:

- V3 Repeater Policy,
- V3 Power Monitor,
- V3 Diagnostic Log,
- V3 Mesh Monitor,
- V3 Position-/Phone-Position-Logik,
- V3 Service Pages / Service Web,
- Light-Sleep-/Wake-Up-spezifische Änderungen,
- eigene V3 Hardware-/Runtime-Schicht.

### Drone Repeater

Branch: `heltec-tracker-v11-drone-repeater`

Der Branch ist gegenüber dem aktuellen Tracker-Zweig stark zurückliegend, besitzt aber ca. 50 eigene Commits gegenüber dem Tracker-Merge-Base und enthält wichtige rollenbezogene Funktionen:

- `HeltecTrackerV11DroneRepeaterPolicy`,
- Drone Diagnostic Log,
- Drone Mesh Health,
- Drone Power Monitor,
- Drone Status Pages,
- Drone System Health,
- Drone-spezifische Runtime-/Service-Patches.

Die Drone-Firmware ist daher kein geeigneter Basispunkt für den Unified Core. Ihre Funktionsblöcke werden später gezielt als `DRONE_REPEATER`-Rolle in den Tracker-Build migriert.

## Zielmodell

```text
JARN-MESH Unified Core
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

Beispiel:

```text
Tracker V1.1 + DRONE_REPEATER
=> Drone-Repeater-Verhalten

Tracker V1.1 + TAK_TRACKER
=> Fahrzeug-/Tracker-Verhalten

V3 ohne GPS + TAK_REPEATER
=> Repeater-Verhalten

V3 + externes GPS + TAK_TRACKER
=> später möglich, sofern Capability-Matrix vollständig erfüllt
```

## Jarnsen Node Service Tool

Es bleibt genau ein Service Tool: **Jarnsen Node Service Tool**.

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

Diese Informationen sollen in die Nodeübersicht aufgenommen werden.

Wichtig: Das Tool hat weiterhin eine eigene Versionslinie und wird nicht von Tracker-, V3- oder Drone-Firmwareversionen bestimmt.

## Erste Funktionsklassifizierung

### Gemeinsamer Core – Kandidaten

- BLE-Grundlogik,
- WLAN,
- Captive Portal / Service Web-Grundsystem,
- OTA / GitHub Update,
- Build-/Firmware-Metadaten,
- Diagnose-Grundframework,
- Logging-Grundframework,
- Live Display-Grundsystem,
- Service-Protokoll,
- gemeinsame Mesh-/TAK-Hilfsfunktionen,
- gemeinsame Display-Helfer,
- gemeinsame Node-/Firmwareinformationen.

### Hardware Layer – Kandidaten

Tracker V1.1:

- integriertes GPS,
- Tracker-Pinbelegung,
- Motion-/Wake-Up-Hardware,
- Tracker-Power-Hardware.

Heltec V3:

- V3-Pinbelegung,
- V3-spezifischer Button/Wake-Up,
- V3 Power Hardware,
- extern anschließbares GPS als optionale Peripherie.

### Rollen – Kandidaten

TAK_TRACKER:

- Bewegungs-/Positionsstrategie,
- Tracker-spezifische Sende-/Standlogik.

TAK_REPEATER:

- Repeater Policy,
- Repeater Power-/Sleep-Strategie.

DRONE_REPEATER:

- Drone Repeater Policy,
- Drone Power Policy,
- Drone Status-/System-Health-spezifisches Verhalten.

## Migrationsregel

Kein bestehender Tracker-, V3- oder Drone-Code wird in Phase 0 funktional verändert.

Keine Altimplementierung wird gelöscht, bevor die neue gemeinsame Implementierung auf den betroffenen Hardware-Builds erfolgreich kompiliert und getestet wurde.

Der Umbau erfolgt in Phasen:

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

## Phase-0-Entscheidung

- Integrationsbranch: erstellt
- Basis: Tracker V1.1 Branch
- Tracker-, V3- und Drone-Produktionsbranches: bleiben unangetastet
- Funktionaler Firmwarecode in Phase 0 geändert: **NEIN**
- Nächster Schritt: detaillierte Funktionsmatrix und Duplikat-Inventur vervollständigen; danach Phase 1 starten.
