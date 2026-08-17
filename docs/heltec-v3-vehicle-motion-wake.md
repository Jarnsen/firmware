# Heltec V3 vehicle motion wake

This branch adds a vehicle-tracker power profile for the Heltec WiFi LoRa 32 V3.

## Hardware

- Original user/PRG button stays on GPIO0.
- SW-18010P vibration switch uses GPIO7 as an additional active-LOW wake source.
- 100 kOhm from 3V3 to GPIO7.
- SW-18010P from GPIO7 to GND.
- Optional/recommended 100 nF ceramic capacitor from GPIO7 to GND.

## Behaviour

- TRACKER or TAK_TRACKER + Power Saving enables the vehicle logic.
- Movement wakes the ESP32-S3 through EXT0 on GPIO7.
- While vibration continues, deep sleep requests are deferred so Bluetooth can stay available for the phone and phone-provided position updates.
- After 120 seconds without vibration, the latest position is sent once and the node enters deep sleep.
- The configured `position.position_broadcast_secs` value is used as the stationary timer wake interval (target: 3600 seconds / 1 hour).
- On a timer wake, the last parked position retained in RTC memory is restored and re-broadcast, then the node returns to sleep.
- USB power is treated as service/configuration mode and suppresses deep sleep.

## Required Meshtastic settings

The custom motion input is **not** the Meshtastic user button. Keep the normal button setting on GPIO0:

```bash
meshtastic --set device.button_gpio 0
```

Recommended vehicle tracker settings:

```bash
meshtastic --set device.role TRACKER
meshtastic --set power.is_power_saving true
meshtastic --set bluetooth.enabled true
meshtastic --set position.position_broadcast_secs 3600
meshtastic --set position.position_broadcast_smart_enabled true
meshtastic --set position.broadcast_smart_minimum_distance 75
meshtastic --set position.broadcast_smart_minimum_interval_secs 30
```

The Heltec V3 has no onboard GNSS. Fresh moving positions therefore come from the connected phone. During stationary timer wakes, the last parked position is deliberately re-used until the phone provides a newer position on the next movement wake.
