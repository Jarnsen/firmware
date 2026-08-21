# Heltec Wireless Tracker V1.1 – Drone Repeater

Dedicated airborne profile for `heltec-tracker-v11-drone-repeater`.

## Purpose

The Tracker V1.1 is mounted on a drone and performs two jobs at the same time:

1. Track the drone using the onboard GNSS receiver.
2. Extend the Meshtastic mesh as a `ROUTER_LATE` node.

The drone profile is deliberately independent of the vehicle `TAK` / `TAK_TRACKER` motion-sensor and park-sleep logic.

## Default airborne profile

- Meshtastic role: `ROUTER_LATE`
- Rebroadcast mode: `ALL`
- GNSS: enabled continuously
- Fixed position: disabled
- Smart position: enabled
- Smart minimum distance: **25 m**
- Smart minimum interval: **10 s**
- Stationary/ground heartbeat: **30 s**
- Power saving: disabled while powered
- Deep sleep: not used
- Light sleep: not used
- Wi-Fi: disabled
- LED heartbeat: disabled
- Display: stock Meshtastic UI, 20 s timeout
- Bluetooth: off by default

## GPIO0 service

The normal Meshtastic button/display behavior is retained. In addition, the first GPIO0 press starts Bluetooth service.

- Bluetooth idle timeout: 120 s since the last real button/BLE activity
- Absolute Bluetooth service cap: 15 min
- A technically connected but idle phone does not by itself reset the timeout; actual BLE traffic does.

This avoids the custom overlay/display ownership used by the vehicle profiles and keeps the drone UI simple and reliable.

## Position behavior

The initial flight-test profile uses 25 m / 10 s rather than the vehicle tracker's 75 m / 30 s. At higher airspeed the 10-second minimum interval becomes the limiting factor, preventing excessive airtime while still producing a useful flight track.

A later revision may adapt the interval between 5 and 30 seconds based on speed and channel utilization, but the first hardware test intentionally keeps the logic deterministic.

## Build artifact

GitHub Actions workflow:

`Build Heltec Tracker V1.1 Drone Repeater`

Artifacts:

- `heltec-tracker-v11-drone-repeater.update.bin`
- `heltec-tracker-v11-drone-repeater.factory.bin`
- `heltec-tracker-v11-drone-repeater.elf`
