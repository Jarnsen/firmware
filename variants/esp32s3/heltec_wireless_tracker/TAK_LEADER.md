# Heltec Wireless Tracker V1.1 - TAK leadership profile

This branch supports two field roles on the same Tracker V1.1 hardware:

- `TAK` = leadership element with ATAK phone available on demand.
- `TAK_TRACKER` = autonomous vehicle tracker using the SW-18010P parked deep-sleep profile.

## TAK leadership behavior

Use the Heltec Wireless Tracker V1.1 with role `TAK` when the vehicle/leadership element must:

- keep receiving LoRa traffic even while the ATAK phone is off;
- maintain its own position from the onboard UC6580 GNSS without the phone;
- continue transmitting its own position according to PositionModule settings;
- keep Bluetooth and the display off when ATAK is not intentionally being used;
- enter ESP32 light sleep rather than the custom parked deep sleep used by `TAK_TRACKER`.

The TAK leadership policy automatically enforces at runtime:

- power saving ON;
- Wi-Fi OFF;
- 1-second Bluetooth timeout for unattended packet wakes;
- 1-second minimum wake interval;
- long light-sleep timer windows (3600 s), while LoRa IRQ remains able to wake immediately;
- display OFF outside intentional user service.

## ATAK / GPIO0 service

Keep Bluetooth enabled in the saved Meshtastic configuration so the BLE stack remains available after boot.

When ATAK is needed:

1. Turn on the ATAK phone.
2. Press GPIO0 once on the Tracker V1.1.
3. The node opens a 120-second Bluetooth/ATAK service window.
4. The display shows a short diagnostic banner (20 s normally, 10 s at <=20% battery).
5. Press GPIO0 again to restart the 120-second window if a longer ATAK session is needed.

While the service window is active the firmware periodically refreshes PowerFSM so the node cannot fall into light sleep. Outside the service window BLE is forced back off at the next scheduler opportunity.

## Recommended TAK settings

- Device role: `TAK`
- Power saving: ON (also enforced by the profile)
- GPS mode: ENABLED
- Fixed position: OFF
- Smart position: ON
- Smart minimum distance: 75 m
- Smart minimum interval: 30 s
- Button GPIO: 0
- Bluetooth: ON in saved config
- Wi-Fi: OFF (also enforced by the profile)
- LED heartbeat: OFF

The phone can be completely off. LoRa and onboard GNSS remain available; when the phone is later connected through the GPIO0 service window, the node can provide its accumulated mesh state to the Meshtastic/ATAK client.
