# Heltec Wireless Tracker V1.1 - TAK leadership profile

This branch supports two field roles on the same Tracker V1.1 hardware:

- `TAK` = leadership element with ATAK phone available on demand.
- `TAK_TRACKER` = autonomous vehicle tracker using the SW-18010P parked deep-sleep profile.

## Wiring and service menu

Full illustrated wiring guide: [`docs/heltec-tracker-v11-wiring.md`](../../../docs/heltec-tracker-v11-wiring.md)

GPIO0 Bluetooth/service/settings guide: [`docs/heltec-tracker-v11-service-menu.md`](../../../docs/heltec-tracker-v11-service-menu.md)

The `TAK` and `TAK_TRACKER` roles use the same SW-18010P circuit on GPIO7; only their sleep behavior differs. GPIO0 remains the user/service button.

## TAK leadership behavior

Use the Heltec Wireless Tracker V1.1 with role `TAK` when the vehicle/leadership element must:

- keep receiving LoRa traffic even while the ATAK phone is off;
- maintain its own position from the onboard UC6580 GNSS without the phone;
- continue transmitting its own position autonomously;
- keep Bluetooth and the display off when ATAK is not intentionally being used;
- enter ESP32 light sleep rather than the custom parked deep sleep used by `TAK_TRACKER`.

## Motion-aware light sleep

GPIO7 is enabled as an ESP32 light-sleep wake source for the TAK leadership role.

- First vibration wakes the leadership node from light sleep.
- The default `NORMAL` sensitivity confirms movement after **3 falling edges within 3 seconds**.
- Sensitivity is adjustable in the GPIO0 service menu: `VERY SENS` 2/3 s, `SENSITIVE` 3/4 s, `NORMAL` 3/3 s, `ROBUST` 4/3 s.
- The wake-causing LOW level is counted as the first candidate pulse even if it occurred before the normal Arduino ISR resumed after light sleep.
- Once confirmed, the firmware vetoes CPU light sleep while vibration continues so the GNSS parser and PositionModule remain operational.
- Bluetooth and the display stay OFF during movement-only operation.
- After 120 seconds without vibration, the sleep veto is released and the leadership node returns to always-listening light sleep.
- A GPIO7 LOW condition lasting 30 seconds disables motion wake temporarily until the input recovers HIGH, preventing a stuck sensor from causing a wake loop.

LoRa remains available throughout light sleep and can wake the ESP32 on received radio traffic.

## Autonomous position policy

Defaults:

- onboard GNSS enabled;
- fixed position OFF;
- Smart Position ON;
- minimum movement distance **75 m**;
- minimum Smart Position interval **30 s**;
- autonomous stationary position heartbeat **60 min**.

The distance, Smart Position interval and heartbeat interval can be changed in the local GPIO0 menu. Available presets are 50/75/100/150 m, 30/45/60/90 s and 30/60/120/240 min respectively. Changes are persisted in ESP32 NVS.

Normal PositionModule behavior handles movement broadcasts while the node is awake. The additional heartbeat ensures that the leadership element still reports itself even when the ATAK phone is completely off.

## Power behavior

The policy automatically enforces at runtime:

- power saving ON;
- Wi-Fi OFF;
- 1-second Bluetooth timeout for unattended packet wakes;
- 1-second minimum wake interval;
- light sleep while stationary, with LoRa IRQ able to wake the CPU;
- display OFF outside intentional user service;
- LED heartbeat OFF;
- triple-click GPS toggle disabled to avoid accidental GNSS shutdown in the field.

A preflight sleep observer vetoes **light sleep only** while movement is being confirmed, confirmed movement is active, or the deliberate ATAK/service window is open. True deep sleep/shutdown requests such as critical-battery protection are never vetoed.

## ATAK / GPIO0 service

Keep Bluetooth enabled in the **saved Meshtastic configuration** so the ESP32 BLE stack remains allocated after boot. Operationally the firmware forces Bluetooth OFF outside deliberate service.

When ATAK or configuration access is needed:

1. Press GPIO0 once.
2. The node opens a **120-second Bluetooth/ATAK/settings window** and shows STATUS.
3. Connect the Meshtastic app or ATAK/Meshtastic client via Bluetooth.
4. Further **short presses** step through the local settings pages.
5. A **long press of about 1.2 s** changes the value on an editable page.
6. At the end of 120 seconds Bluetooth and the display are explicitly switched OFF again.

The local pages are STATUS, MOTION, MIN DISTANCE, MIN INTERVAL and HEARTBEAT. Normal Meshtastic settings such as channel, PSK, region, node name and TAK configuration remain editable through the phone during the same Bluetooth window.

## Required / recommended saved settings

- Device role: `TAK`
- Bluetooth: ON in saved config
- Button GPIO: 0

The local Tracker V1.1 presets override the corresponding movement/distance/interval/heartbeat runtime values. The phone can otherwise be completely off; LoRa and onboard GNSS remain available autonomously.
