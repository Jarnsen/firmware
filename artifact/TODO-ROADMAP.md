# Heltec V3 Repeater - TODO Roadmap

Diese Datei ist die feste Entwicklungs-Roadmap fuer den V3 und wird mit jedem Firmware-Artefakt ausgeliefert.

## Arbeitsregel

- Neue Punkte bleiben als `[ ]` offen.
- Erledigte Punkte werden nicht geloescht.
- Nach erfolgreichem Hardwaretest wird der Punkt auf `[x]` gesetzt und in **Completed** verschoben.
- Wenn sinnvoll, Build/SHA oder Datum hinter dem erledigten Punkt notieren.
- Neue Funktionen erst beginnen, wenn der aktuelle Basis-/Langzeittest stabil ist.

## Gate vor weiterer Entwicklung

- [ ] Komplette V3-Testcheckliste ohne kritischen Fehler bestanden.
- [ ] 24-72 h Langzeittest ohne unerwarteten Reset, BLE-/LoRa-Recovery-Schleifen oder auffaellige Power-Daten bestanden.

## Prioritaet 1 - INA226 / echte Power-Messung

- [ ] INA226-Hardware am V3 anschliessen und Backend aktivieren.
- [ ] Shuntwert und Messbereich sauber kalibrieren; keine automatisch geratenen Kalibrierwerte verwenden.
- [ ] Strom, Leistung, mAh und Wh als echte Messwerte erfassen.
- [ ] Interne Battery-%-/Spannungswerte mit INA226 vergleichen.
- [ ] `Source: INTERNAL` automatisch auf echte INA226-Quelle umstellen, sobald Hardware validiert ist.
- [ ] Power Statistics um reale Durchschnittsstroeme und Energie erweitern.

## Prioritaet 2 - Verbrauchsmodell / Laufzeitprognose

- [ ] Reale Verbrauchswerte fuer LISTEN, SERVICE, BLE, DISPLAY und Position-TX lernen.
- [ ] Durchschnittsstrom und Energie pro Betriebszustand auswerten.
- [ ] Restlaufzeit aus realem Verbrauch + Batteriekapazitaet berechnen.
- [ ] Laden/USB/Batteriewechsel weiterhin sicher vom Entladelernen trennen.

## Prioritaet 3 - System Health / Selbstdiagnose

- [ ] System-Health-Zusammenfassung ohne neue Hauptseite integrieren.
- [ ] Resetgrund, Watchdog-/Crash-Recoveries und laengste Uptime erfassen.
- [ ] Minimum Free Heap und relevante Recovery-Zaehler erfassen.
- [ ] LoRa- und BLE-Recovery-Anzahl im Diagnose-Log ausgeben.
- [ ] Klaren Status `SYSTEM HEALTH: OK/DEGRADED` ableiten.

## Prioritaet 4 - Mesh Health erweitern

- [ ] Direct Nodes 24 h erfassen.
- [ ] RX 24 h erfassen.
- [ ] Median RSSI/SNR 24 h fuer direkte Nachbarn berechnen.
- [ ] Staerksten und schwaechsten stabilen direkten Node erfassen.
- [ ] Anteil Direct vs. Relayed auswerten, ohne Relay-Paketen falsche RSSI/SNR-Werte zuzuordnen.

## Prioritaet 5 - Antennentest erweitern

- [ ] Aktuellen RX-only A/B-Test auf Langzeitstabilitaet pruefen.
- [ ] Spaeter optional bidirektionalen Test mit kontrolliertem Referenznode entwickeln.
- [ ] Remote-RSSI, Remote-SNR und Packet Loss erfassen.
- [ ] A/B-Vergleich weiterhin als relativen Linkvergleich darstellen, nicht als erfundene dBi-Messung.

## Prioritaet 6 - Firmware-/Konfigurations-Sicherheitsnetz

- [ ] Eigene Feature-/Schema-Version fuer persistente V3-Daten einfuehren.
- [ ] NVS-Migration fuer spaetere Datenstruktur-Aenderungen vorsehen.
- [ ] Build-ID, Build-Datum und eigene Feature-Version im Diagnose-Log ausgeben.
- [ ] Veraltete oder inkompatible persistente Daten niemals stillschweigend falsch interpretieren.

## Prioritaet 7 - Passiver Boot-Selbsttest

- [ ] Beim Boot NVS/Preferences pruefen.
- [ ] Display-Initialisierung pruefen.
- [ ] LoRa-Initialisierung pruefen.
- [ ] interne Power-Messung pruefen.
- [ ] INA226 als `OK` oder `NOT INSTALLED` erkennen.
- [ ] persistenten Antenna-Swap-TX-Lock pruefen.
- [ ] Ergebnis kompakt ins Diagnose-Log schreiben.

## Nicht voreilig erweitern

- Keine zusaetzlichen Hauptseiten ohne echten Mehrwert.
- Keine automatische Antennenerkennung ohne echte HF-Messhardware.
- Keine aggressiven adaptiven Funkmodi, solange die Basis nicht langfristig stabil ist.
- Keine neuen Power-Optimierungen nur aufgrund theoretischer Annahmen; zuerst messen.

## Completed

_Noch keine neuen Roadmap-Punkte abgeschlossen. Aktueller Schritt: Basis- und Langzeittest._
