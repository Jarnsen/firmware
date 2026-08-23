# INA226 Anschlussplan – Heltec V3 Repeater

Dieser Plan gehört zum Branch `heltec-v3-repeater-light-sleep` und wird mit dem Firmware-Artefakt ausgeliefert.

## Verwendetes Modul

**Produktname des bestellten Moduls:**

`Hailege 2pcs INA226 I2C IIC Bidirektionaler Stromüberwachungssensor Leistungsmonitor-Sensor mit Alarmfunktion`

**Interne Modellbezeichnung für dieses Projekt:**

`Hailege INA226 R100 8-Pin Breakout 20.5x19.4`

Damit ist genau das bestellte Modul gemeint, das auf den Produktbildern zu sehen ist:

- Hersteller/Marke: `Hailege`
- Lieferumfang: `2 Stück`
- Messchip: INA226
- Shunt: `R100 = 0,1 Ohm`
- Abmessungen: ca. `20,5 x 19,4 mm`
- 8 Anschlüsse: `IN+`, `IN-`, `VBS`, `ALE`, `SDA`, `SCL`, `GND`, `VCC`
- Standard-I2C-Adresse: `0x40` bei A0/A1 in Default-Stellung
- separater `VBS/VBUS`-Anschluss für die Busspannungsmessung
- `ALE/ALERT` vorhanden, für unsere Firmware nicht erforderlich
- keine sichtbare Power-LED auf diesem Breakout

Die Produktbezeichnung enthält keine separate numerische Modellnummer. Für dieses Projekt wird das Board deshalb zusätzlich über Hersteller, R100-Shunt, 8-Pin-Belegung und Abmessungen eindeutig identifiziert.

## Firmwarekalibrierung

Die Firmwarekalibrierung gilt für:

- INA226
- I2C-Adresse `0x40`
- Shunt `R100 = 0,1 Ohm`
- positive Stromrichtung: Quelle/Akku -> IN+ -> R100 -> IN- -> Heltec V3

**Wichtig:** Hat ein anderes INA226-Modul einen anderen Shunt, z. B. `R010 = 0,01 Ohm`, darf es nicht mit dieser R100-Kalibrierung verwendet werden. Dann muss zuerst die Firmwarekalibrierung angepasst werden.

## I2C- und Messanschluss

| INA226-Modul | Heltec V3 / Strompfad | Hinweis |
|---|---|---|
| VCC | 3V3 | INA226-Logik mit 3,3 V versorgen |
| GND | GND | gemeinsame Masse |
| SDA | GPIO41 / SDA | externer I2C-Bus |
| SCL | GPIO42 / SCL | externer I2C-Bus |
| VBS / VBUS | IN- / V3 BAT+ | Busspannung auf der Lastseite messen |
| ALE / ALERT | nicht anschließen | wird von unserer Firmware nicht benötigt |
| IN+ | Akku/Quelle + | Eingang vor dem Shunt |
| IN- | V3 BAT+ | Ausgang nach dem Shunt |

**VBS/VBUS muss angeschlossen werden.** Ohne diese Verbindung kann der INA226 zwar den Shuntstrom erfassen, aber Busspannung, Leistung und Wh wären nicht korrekt.

Der Heltec V3 verwendet für das OLED intern GPIO17/GPIO18. **INA226 nicht an GPIO17/18 anschließen.** Für externe I2C-Geräte verwenden wir GPIO41/GPIO42.

## Strompfad – Akkubetrieb

```text
Akku +
  |
  v
INA226 IN+
  |
  [ R100 = 0,1 Ohm ]
  |
INA226 IN- ---------------------> Heltec V3 BAT+
  |
  +----------------------------> INA226 VBS / VBUS

Akku - ------------------------> Heltec V3 GND
                  |
                  +------------> INA226 GND

Heltec V3 3V3 -----------------> INA226 VCC
Heltec V3 GPIO41 --------------> INA226 SDA
Heltec V3 GPIO42 --------------> INA226 SCL

INA226 ALE / ALERT ------------> frei lassen
```

So angeschlossen ist der Verbrauch des V3 vom Akku **positiver Strom**. Bei vertauschtem IN+/IN- wird die Stromrichtung negativ angezeigt.

## Warum VBS an die Lastseite gehört

Der INA226 misst den Spannungsabfall am R100 zwischen `IN+` und `IN-` für die Stromberechnung. Die eigentliche Busspannung wird separat über `VBS/VBUS` gemessen.

Für unsere Leistungs- und Energieauswertung soll die Spannung verwendet werden, die tatsächlich am V3 nach dem Shunt anliegt. Deshalb:

```text
VBS / VBUS -> IN- / V3 BAT+
```

Damit gilt näherungsweise:

`Leistung des V3 = Lastseitige Busspannung x gemessener Strom`

## Externe Versorgung statt Akku

```text
Quelle + -> INA226 IN+ -> INA226 IN- -> V3 Versorgung +
                              |
                              +-------> INA226 VBS / VBUS

Quelle - ----------------------------> V3 GND / INA226 GND
```

Die zulässige Spannung des INA226 und des verwendeten Heltec-V3-Versorgungseingangs beachten.

## USB-Hinweis

Wenn der V3 zusätzlich über USB versorgt wird, kann ein Teil oder die gesamte Energie den Shunt umgehen. Eine INA226-Messung im Akku-Pluspfad ist dann **keine reine Batterieverbrauchsmessung**. Für Laufzeit- und Verbrauchstests deshalb nach Möglichkeit ohne parallele USB-Versorgung messen.

## Eigenverbrauch des Messmoduls

Da dieses Modul keine sichtbare Power-LED besitzt, besteht der zusätzliche Dauerverbrauch im Wesentlichen aus dem INA226 selbst und den I2C-Pullups.

Für die reale Laufzeit interessiert uns der Verbrauch des **kompletten fertigen Systems einschließlich INA226**. Genau dieser Gesamtverbrauch soll später ausgewertet werden.

## Firmwareverhalten V3

Implementiert/vorgesehen ist:

- automatische INA226-Erkennung auf `0x40`
- R100-Kalibrierung
- automatischer Fallback auf interne Meshtastic-Batteriedaten, wenn kein INA226 gefunden wird
- Busspannung über VBS/VBUS
- Strom und Leistung
- aufsummierte mAh und mWh
- Durchschnittswerte für Listen, Service, BLE und Display
- verdichtete Werte im Diagnostic Log statt sekündlicher Flash-Schreibvorgänge
- keine Änderung an Repeater-, LoRa-, BLE-, Display-, Positions- oder Antennen-TX-Lock-Logik durch die Messfunktion

## Vor dem ersten Einschalten prüfen

1. Modul entspricht `Hailege INA226 R100 8-Pin Breakout 20.5x19.4`.
2. Shunt-Aufdruck wirklich `R100`.
3. INA226-Adresse `0x40`.
4. VCC an 3V3.
5. GND gemeinsam.
6. SDA an GPIO41, SCL an GPIO42.
7. VBS/VBUS an IN- bzw. V3 BAT+.
8. Akku/Quelle + zuerst an IN+, von IN- weiter zum V3.
9. ALE/ALERT bleibt frei.
10. Keine parallele Versorgung am Shunt vorbei, wenn der Gesamtverbrauch gemessen werden soll.
