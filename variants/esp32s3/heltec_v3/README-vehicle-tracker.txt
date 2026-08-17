Heltec V3 vehicle tracker build

GPIO0: original Meshtastic user button
GPIO7: SW-18010P motion wake (active LOW)

Wiring:
3V3 -- 100k -- GPIO7
GPIO7 -- SW-18010P -- GND
GPIO7 -- 100nF ceramic -- GND

Keep device.button_gpio = 0.
Default motion quiet timeout in this branch: 120 seconds.
Stationary sleep/wake interval follows position.position_broadcast_secs.
