# Jarnsen Node Service Tool v3 – Framework7 UI

## Ziel

Die sichtbare Desktop-Oberfläche wird vollständig mit Framework7 Core im iOS-Theme gerendert. Der bestehende Python-Servicekern bleibt für BLE, USB, OTA, Firmware, Logimport, SQLite, Profile und Diagnose erhalten.

## Architektur

```text
Framework7 9.1.3 / iOS UI
        │
        │ fetch(JSON), nur 127.0.0.1 + Zufallstoken
        ▼
Loopback API Bridge
        │
        │ Tk-main-thread dispatch
        ▼
Bestehender Python Service Core
        │
        ├─ BLE / PIN 240180 / Auto Log Queue
        ├─ USB / Serial / ESPTool
        ├─ OTA / GitHub Firmware
        ├─ SQLite NodeRepository / Logs / Historie
        ├─ Profile / Readback / Virgin Provisioning
        └─ Live / Diagnose / Position
```

Der alte Tk-Aufbau wird im Backend-Prozess verborgen. Er dient nur noch als Kompatibilitätsschicht für bewährte Servicefunktionen und ist nicht die normale Benutzeroberfläche.

## Frontend

- `index.html` – Framework7 Desktop-Shell
- `app.css` – macOS/iOS-inspirierte Desktop-Anpassungen
- `app.js` – Node-Store, Filter, Inspector, Actions, Unterbereiche und API-Anbindung
- `vendor/` – wird im Release-Build mit Framework7 9.1.3 gefüllt und offline in die EXE gepackt

## Desktop Runtime

`JARNSEN_FRAMEWORK7_SERVICE_TOOL.py` startet zwei lokale Prozesse:

1. sichtbares pywebview/WebView2-Fenster mit Framework7
2. verborgenes Python-Servicebackend mit Tk-mainloop und lokaler API

Die API bindet ausschließlich an `127.0.0.1` und verlangt pro Start ein zufälliges Token.

## Release-Build

Der v3-Preview-Workflow installiert Framework7 9.1.3 über npm, kopiert CSS/JS in `vendor/`, packt WebView + Webassets + Python-Servicekern als portable Windows-EXE und führt zwei Tests aus:

- Asset-/Framework7-Self-Test der gepackten EXE
- Start des verborgenen Python-Backends inklusive `/health` und `/api/state`
