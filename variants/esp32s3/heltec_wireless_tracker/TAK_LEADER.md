# Heltec Wireless Tracker V1.1 - TAK leadership profile

This branch supports two field roles on the same Tracker V1.1 hardware:

- `TAK` = leadership element with ATAK phone available on demand.
- `TAK_TRACKER` = autonomous vehicle tracker using the SW-18010P parked deep-sleep profile.

## TAK leadership behavior

Use the Heltec Wireless Tracker V1.1 with role `TAK` when the vehicle/leadership element must:

- keep receiving LoRa traffic even while the ATAK phone is off;
- maintain its own position from the onboard UC6580 GNSS without the phone;
- continue transmitting its own position autonomously;
- keep Bluetooth and the display off when ATAK is not intentionally being used;
- enter ESP32 light sleep rather than the custom parked deep sleep used by `TAK_TRACKER`.

Use the same SW-18010P circuit as the Kfz trackers on GPIO7 (100 kOhm pull-up to 3V3, sensor to GND, recommended 100 nF to GND). GPIO0 remains the user/service button.

## Motion-aware light sleep

GPIO7 is also enabled as an ESP32 light-sleep wake source for the TAK leadership role.

- First vibration wakes the leadership node from light sleep.
- Movement is confirmed after 3 falling edges within 3 seconds, matching the Kfz tracker logic.
- Once confirmed, the firmware keeps the CPU operational while vibration continues so PositionModule can evaluate Smart Position normally.
- Bluetooth and the display stay OFF during this movement-only wake state.
- After 120 seconds without vibration, the leadership node returns to always-listening light sleep.
- A GPIO7 LOW condition lasting 30 seconds disables the motion wake temporarily until the input recovers HIGH, preventing a stuck sensor from causing a wake loop.

LoRa remains available throughout light sleep and can wake the ESP32 immediately on received radio traffic.

## Autonomous position policy

The TAK leadership profile enforces:

- onboard GNSS enabled;
- fixed position OFF;
- Smart Position ON;
- minimum movement distance 75 m;
- minimum Smart Position interval 30 s;
- a 3600 s autonomous position heartbeat so a leadership element still reports itself even when the ATAK phone is completely off.

Normal PositionModule behavior handles movement broadcasts while the node is awake. The added hourly heartbeat avoids relying on the much longer generic stationary-position floor.

## Power behavior

The policy automatically enforces at runtime:

- power saving ON;
- Wi-Fi OFF;
- 1-second Bluetooth timeout for unattended packet wakes;
- 1-second minimum wake interval;
- 3600-second light-sleep service timer, while LoRa IRQ remains able to wake immediately;
- display OFF outside intentional user service;
- LED heartbeat OFF;
- triple-click GPS toggle disabled to avoid accidental GNSS shutdown in the field.

## ATAK / GPIO0 service

Keep Bluetooth enabled in the saved Meshtastic configuration so the BLE stack remains available after boot.

When ATAK is needed:

1. Turn on the ATAK phone.
2. Press GPIO0 once on the Tracker V1.1.
3. The node opens a 120-second Bluetooth/ATAK service window.
4. The display shows a short diagnostic banner (20 s normally, 10 s at <=20% battery).
5. Press GPIO0 again to restart the 120-second window if a longer ATAK session is needed.

While the service window is active the firmware refreshes PowerFSM every 500 ms, which prevents the intentionally short unattended Bluetooth timeout from ending an active ATAK session. Outside the service window BLE is forced back off at the next scheduler opportunity.

## Required / recommended saved settings

- Device role: `TAK`
- Bluetooth: ON in saved config
- Button GPIO: 0

The profile enforces the power, GNSS, Smart Position and Wi-Fi settings above at runtime.

The phone can be completely off. LoRa and onboard GNSS remain available; when the phone is later connected through the GPIO0 service window, the node can provide its accumulated mesh state to the Meshtastic/ATAK client.