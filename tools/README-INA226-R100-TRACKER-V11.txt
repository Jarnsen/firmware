Heltec Wireless Tracker V1.1 - INA226 R100 Anschlussplan
======================================================

Zweck
-----
Optionaler INA226-Strom-/Leistungssensor fuer die Tracker-Power-Statistik.
Die Firmware muss auch ohne INA226 funktionieren. INA226 wird erst in den
Tracker-Einstellungen aktiviert, wenn die Hardware wirklich angeschlossen ist.

Passendes Modul
---------------
- INA226
- integrierter Shunt: R100 = 0,1 Ohm
- I2C-Adresse: standardmaessig 0x40
- 1S Li-Ion/LiPo: geeignet (ca. 3,0 bis 4,2 V)

WICHTIG: INA226 VCC ist die 3,3-V-Logikversorgung. Akku+ NICHT an VCC anschliessen.
Akku+ wird nur ueber IN+ / IN- und den R100-Shunt zum Tracker gefuehrt.

I2C / Logik
-----------
INA226 VCC   -> Heltec 3V3
INA226 GND   -> Heltec GND / Akku-
INA226 SDA   -> Heltec SDA = GPIO45
INA226 SCL   -> Heltec SCL = GPIO46
INA226 ALERT -> nicht anschliessen (NC)

Strompfad / Shunt
-----------------

  1S Li-Ion Akku

  Akku +  ----------------->  INA226 IN+
                                  |
                                  |  R100 / 0,1 Ohm Shunt
                                  |
                              INA226 IN-
                                  |
                                  +-----------------> Heltec BAT + / JST +

  Akku -  -----------------------------------------> Heltec BAT - / JST -
      |
      +--------------------------------------------> INA226 GND

Kurzfassung
-----------
Akku+ -> INA226 IN+ -> R100 -> INA226 IN- -> Heltec Akku+
Akku- --------------------------------------> Heltec Akku-
                                              + INA226 GND
Heltec 3V3 -> INA226 VCC
GPIO45/SDA -> INA226 SDA
GPIO46/SCL -> INA226 SCL
ALERT      -> offen lassen

Hinweise
--------
1. Der Shunt muss in Reihe in der PLUS-Leitung liegen. Nicht parallel anschliessen.
2. Gemeinsame Masse ist erforderlich: Akku-, Heltec GND und INA226 GND.
3. Bei einem Modul mit A0/A1-Adresspads die Standardbelegung unveraendert lassen,
   damit die Firmware Adresse 0x40 verwendet.
4. Auf dem Messwiderstand sollte R100 stehen. R100 bedeutet 0,1 Ohm.
5. Erst nach korrektem Anschluss im Tracker-Menue "INA226 Hardware" auf ON stellen.
6. Ist INA226 auf ON gestellt, aber nicht erreichbar, soll die Firmware den Zustand
   als MISSING anzeigen und weiterhin mit der internen Batteriespannung arbeiten.
7. Die interne Heltec-Batteriespannungsmessung bleibt auch mit INA226 aktiv.

Pin-Quelle Tracker V1.1
-----------------------
SDA = GPIO45
SCL = GPIO46

Stand: 2026-08-22
