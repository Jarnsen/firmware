# INA226 Anschlussplan – Heltec V3 Repeater

Dieser Plan gehört zum Branch `heltec-v3-repeater-light-sleep` und wird mit dem Firmware-Artefakt ausgeliefert.

## Voraussetzung

Die vorbereitete Firmwarekalibrierung gilt für:

- INA226
- I2C-Adresse `0x40` (A0/A1 in Default-Stellung)
- Shunt `R100 = 0,1 Ohm`
- positive Stromrichtung: Quelle/Akku -> VIN+ -> VIN- -> Heltec V3

**Wichtig:** Hat dein INA226-Modul einen anderen Shunt (z. B. `R010 = 0,01 Ohm`), nicht mit der R100-Kalibrierung verwenden. Dann muss zuerst die Firmwarekalibrierung angepasst werden.

## I2C-Anschluss

| INA226 | Heltec V3 | Hinweis |
|---|---|---|
| VCC | 3V3 | INA226-Logik mit 3,3 V versorgen |
| GND | GND | gemeinsame Masse |
| SDA | GPIO41 / SDA | externer I2C-Bus |
| SCL | GPIO42 / SCL | externer I2C-Bus |

Der Heltec V3 verwendet für das OLED intern GPIO17/GPIO18. **INA226 nicht an den OLED-I2C GPIO17/18 anschließen.** Der für externe Geräte vorgesehene Bus ist GPIO41/GPIO42.

## Strompfad – Akkubetrieb

```text
Akku +
  |
  v
INA226 VIN+ / IN+
  |
  [ R100 Shunt auf dem INA226-Modul ]
  |
INA226 VIN- / IN-
  |
  v
Heltec V3 BAT+

Akku - -----------------------> Heltec V3 GND
                 |
                 +------------> INA226 GND

Heltec V3 3V3 ----------------> INA226 VCC
Heltec V3 GPIO41 -------------> INA226 SDA
Heltec V3 GPIO42 -------------> INA226 SCL
```

So angeschlossen ist der Verbrauch des V3 vom Akku **positiver Strom**. Bei vertauschtem VIN+/VIN- erscheint die Stromrichtung negativ.

## Externe Versorgung statt Akku

Soll der Verbrauch über eine externe Versorgung gemessen werden, muss auch deren Plusleitung durch den Shunt geführt werden:

```text
Quelle + -> INA226 VIN+ -> INA226 VIN- -> V3 Versorgung +
Quelle - -------------------------------> V3 GND
```

Die zulässige Spannung des verwendeten INA226-Moduls und des jeweiligen Heltec-V3-Versorgungseingangs beachten.

## USB-Hinweis

Wenn der V3 zusätzlich über USB versorgt wird, kann ein Teil oder die gesamte Energie den Shunt umgehen. Eine INA226-Messung im Akku-Pluspfad ist dann **keine reine Batterieverbrauchsmessung**. Für Laufzeit-/Verbrauchstests deshalb nach Möglichkeit ohne parallele USB-Versorgung messen. Die Firmware protokolliert den USB-/Ladestatus zusätzlich.

## Firmwareverhalten

Geplant/implementiert wird:

- automatische INA226-Erkennung auf `0x40`
- R100-Kalibrierung
- Fallback auf interne Meshtastic-Batteriedaten, wenn kein INA226 gefunden wird
- Spannung, Strom und Leistung
- aufsummierte mAh und mWh
- verdichtete Werte im Diagnostic Log statt sekündlicher Flash-Schreibvorgänge
- keine Änderung an Repeater-, LoRa-, BLE-, Display- oder Antennen-TX-Lock-Logik durch die Messfunktion

## Vor dem ersten Einschalten prüfen

1. Shunt-Aufdruck wirklich `R100`.
2. INA226-Adresse `0x40`.
3. VCC an 3V3, nicht versehentlich an eine ungeeignete höhere Logikspannung.
4. GND gemeinsam.
5. SDA an GPIO41, SCL an GPIO42.
6. Akku/Quelle + zuerst an VIN+, von VIN- weiter zum V3.
7. Keine parallele Versorgung am Shunt vorbei, wenn der Gesamtverbrauch gemessen werden soll.
