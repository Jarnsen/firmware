# Heltec Tracker V1.1 - TODO Roadmap

Diese Datei ist die feste Entwicklungs-Roadmap fuer den Tracker und wird mit jedem Firmware-Artefakt ausgeliefert.

## Arbeitsregel

- Neue Punkte bleiben als `[ ]` offen.
- Erledigte Punkte werden nicht geloescht.
- Nach erfolgreichem Hardwaretest wird der Punkt auf `[x]` gesetzt und in **Completed** verschoben.
- Wenn sinnvoll, Build/SHA oder Datum hinter dem erledigten Punkt notieren.
- Neue Funktionen erst beginnen, wenn der aktuelle Basis-/Langzeittest stabil ist.

## Gate vor weiterer Entwicklung

- [ ] Komplette Tracker-Testcheckliste ohne kritischen Fehler bestanden.
- [ ] 24-72 h Langzeittest ohne unerwarteten Reset, GPS-/BLE-/LoRa-Probleme oder auffaellige Power-Daten bestanden.

## Prioritaet 1 - INA226 / echte Power-Messung

- [ ] INA226-Hardware am Tracker anschliessen und Backend aktivieren.
- [ ] Shuntwert und Messbereich sauber kalibrieren; keine automatisch geratenen Kalibrierwerte verwenden.
- [ ] Strom, Leistung, mAh und Wh als echte Messwerte erfassen.
- [ ] interne Battery-%-/Spannungswerte mit INA226 vergleichen.
- [ ] Power Statistics auf echte INA226-Daten umstellen, sobald Hardware validiert ist.

## Prioritaet 2 - Verbrauchsmodell / Laufzeitprognose

- [ ] Reale Verbrauchswerte fuer PARKED, MOVING, GNSS, BLE, DISPLAY und Position-TX lernen.
- [ ] Durchschnittsstrom und Energie pro Betriebszustand auswerten.
- [ ] Restlaufzeit aus realem Verbrauch + Batteriekapazitaet berechnen.
- [ ] Laden/USB/Batteriewechsel sicher vom Entladelernen trennen.

## Prioritaet 3 - GPS adaptiv optimieren

- [ ] Aktuelle 75-m-/Bewegungslogik erst im Fahrzeugtest bestaetigen.
- [ ] Bei Bewegungsbeginn weiterhin sofort GPS aktivieren.
- [ ] GPS-Intervall spaeter dynamisch nach Bewegung/Geschwindigkeit anpassen.
- [ ] Bei langsamer Bewegung laengere und bei schneller Bewegung kuerzere Fixintervalle pruefen.
- [ ] Im Stillstand GPS weiter reduzieren, ohne die Stundenmeldung zu gefaehrden.
- [ ] Schlechte Fixes konsequent nicht senden.
- [ ] GPS-Drift im Stillstand staerker filtern, ohne echte Bewegung zu verschlucken.

## Prioritaet 4 - System Health / Selbstdiagnose

- [ ] System-Health-Zusammenfassung ohne unnoetige neue Hauptseite integrieren.
- [ ] Resetgrund, Watchdog-/Crash-Recoveries und laengste Uptime erfassen.
- [ ] Minimum Free Heap und relevante Recovery-Zaehler erfassen.
- [ ] GPS-, BLE- und LoRa-Recovery-Anzahl im Diagnose-Log ausgeben.
- [ ] Ungewoehnlich viele Motion-Wake-Ereignisse erkennen.
- [ ] Klaren Status `SYSTEM HEALTH: OK/DEGRADED` ableiten.

## Prioritaet 5 - Firmware-/Konfigurations-Sicherheitsnetz

- [ ] Eigene Feature-/Schema-Version fuer persistente Tracker-Daten einfuehren.
- [ ] NVS-Migration fuer spaetere Datenstruktur-Aenderungen vorsehen.
- [ ] Build-ID, Build-Datum und eigene Feature-Version im Diagnose-Log ausgeben.
- [ ] Veraltete oder inkompatible persistente Daten niemals stillschweigend falsch interpretieren.

## Prioritaet 6 - Passiver Boot-Selbsttest

- [ ] Beim Boot NVS/Preferences pruefen.
- [ ] Display-Initialisierung pruefen.
- [ ] LoRa-Initialisierung pruefen.
- [ ] GPS/GNSS-Erreichbarkeit pruefen.
- [ ] Motion-Wake-Hardwarestatus pruefen.
- [ ] interne Power-Messung pruefen.
- [ ] INA226 als `OK` oder `NOT INSTALLED` erkennen.
- [ ] Ergebnis kompakt ins Diagnose-Log schreiben.

## Nicht voreilig erweitern

- Keine zusaetzlichen Hauptseiten ohne echten Mehrwert.
- Keine kompliziertere GPS-Automatik, bevor der aktuelle Fahrzeugbetrieb stabil bestaetigt ist.
- Keine aggressiven Stromsparmassnahmen, die Positionsreaktion oder Stundenmeldung verschlechtern.
- Keine neuen Power-Optimierungen nur aufgrund theoretischer Annahmen; zuerst messen.

## Completed

_Noch keine neuen Roadmap-Punkte abgeschlossen. Aktueller Schritt: Basis- und Langzeittest._
