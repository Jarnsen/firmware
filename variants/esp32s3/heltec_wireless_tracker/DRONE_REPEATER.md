# Heltec Wireless Tracker V1.1 – Drone Repeater

Dedicated airborne profile for `heltec-tracker-v11-drone-repeater`.

## Purpose

The Tracker V1.1 is mounted on a drone and performs two jobs at the same time:

1. Track the drone using the onboard GNSS receiver.
2. Extend the Meshtastic mesh as a `ROUTER_LATE` node.

The drone profile is deliberately independent of the vehicle `TAK` / `TAK_TRACKER` motion-sensor and park-sleep logic. The antenna A/B test used by other custom builds is intentionally not part of this profile.

## Airborne profile

- Meshtastic role: `ROUTER_LATE`
- Rebroadcast mode: `ALL`
- GNSS: continuously enabled
- Fixed position: disabled
- Smart position: enabled
- Smart minimum distance: **25 m**
- Stationary/ground heartbeat: **30 s**
- Wi-Fi: disabled in normal operation
- LED heartbeat: disabled
- Display timeout: **20 s on USB / 10 s on battery**
- Bluetooth: off by default
- Deep sleep: never used
- Light sleep: never used

### Adaptive position cadence

The live GNSS speed selects the minimum position interval:

- below 2 km/h: **30 s**
- 2 to below 15 km/h: **10 s**
- 15 to below 40 km/h: **7 s**
- 40 km/h and faster: **5 s**

For moving positions the 25 m movement threshold still has to be reached. A restored GNSS fix queues an immediate fresh position.

Channel utilization protects mesh airtime:

- from 15%: minimum interval 10 s
- from 20%: minimum interval 15 s
- from 25%: minimum interval 30 s and own position transmission waits until TX is allowed

Forwarding as `ROUTER_LATE` is not disabled by the adaptive position scheduler.

## USB and battery operation

The firmware automatically observes the real power source but does not change the mission priorities:

- USB/VBUS available: `USB` or `USB+BAT`
- USB lost with battery present: `BATTERY`
- USB restored: returns automatically to USB operation

LoRa receive/forwarding and GNSS remain fully awake in both USB and battery operation. The dedicated build hook prevents the generic router PowerFSM from putting the drone profile into light/deep sleep when VBUS disappears.

Only side consumers are tightened automatically on battery: the display timeout changes from 20 s to 10 s. BLE remains button-only and Wi-Fi remains disabled. The active priority policy is also written to the flight log.

Power-source changes are recorded persistently:

- `USB_LOST -> BATTERY`
- `USB_RESTORED`
- USB drop/restore counters
- voltage, battery percentage and charging state when available

## Flight / diagnostic log

The persistent flight log records, among other things:

- boot/build/reset reason
- power source and USB changes
- active USB/battery side-consumer priority
- GPS fix acquired/lost/restored
- GPS recovery counter
- position transmissions and reason (`fresh-fix`, `distance`, `ground-heartbeat`)
- speed, channel utilization and active adaptive interval
- LoRa RX/TX and relay counters
- GNSS/BLE/display runtime
- Mesh Health snapshot
- System Health snapshot

The log uses rotating flash files and is exported as the shared `JARNSEN_DIAG_LOG` protocol over USB or BLE.

## Mesh Health

The drone records:

- observed nodes
- active nodes over 15 min / 1 h / 24 h
- direct nodes over 15 min
- RX over 1 h and total RX
- last direct node
- last direct RSSI and SNR
- LoRa TX and relay TX counts

This is intended to show whether the elevated airborne `ROUTER_LATE` node is actually improving mesh reachability.

## System Health

System diagnostics include:

- persistent boot count
- persistent crash-reset count
- reset reason
- minimum free heap
- GPS/BLE/LoRa recovery counters
- compact `OK` / `DEGRADED` state

## Display pages

The normal Meshtastic UI remains available and receives three additional drone pages:

1. **Drone Position** – MGRS, GPS fix, satellites, estimated accuracy, altitude, speed and fix age.
2. **Mesh Health** – nodes, direct contacts, RX, RSSI and SNR.
3. **Drone System** – USB/battery source, battery state, USB drop counters, system health, reset reason, heap, boot count and build SHA.

The MGRS conversion includes the standard Norway and Svalbard UTM zone exceptions.

## GPIO0 service

A GPIO0 press opens the temporary service window.

- Bluetooth idle timeout: 120 s since the last real button/BLE activity
- absolute service cap: 15 min
- real BLE traffic refreshes the idle timer
- an idle connection alone does not keep service open
- if USB CDC is actively connected to a PC when service is opened, the flight-log USB export starts automatically

The shared Jarnsen diagnostic BLE UUIDs support:

- flight-log download
- firmware/build identification
- live display mirror and remote page navigation
- Bluetooth OTA handoff to `otaBTupdate`

For compatibility with the existing Tracker/V3 Node Service Tool, `HOLD`, `HOLDOTA` and `RELEASE` are accepted. They do not alter the drone's no-sleep mission behavior.

## OTA and service package

The build downloads and verifies the Meshtastic ESP32-S3 `otaBTupdate` loader. A one-time USB bootstrap can install:

- main firmware at `0x10000`
- `otaBTupdate.bin` at `0x340000`

After that the BLE service can hand off a verified firmware update to the OTA loader. On battery-only operation, BLE OTA is rejected below 25% battery.

## Build artifact

GitHub Actions workflow:

`Build Heltec Tracker V1.1 Drone Repeater`

The artifact package contains:

- `heltec-tracker-v11-drone-repeater.update.bin`
- `heltec-tracker-v11-drone-repeater.factory.bin`
- `heltec-tracker-v11-drone-repeater.elf`
- `heltec-tracker-v11-drone-repeater.ota.json`
- `otaBTupdate.bin`
- `SHA256SUMS.txt`
- `DRONE_DIAG_LOG_DOWNLOADER.py`
- `drone_log_download.bat`
- `drone-otaBTupdate-installieren.bat`
- `Jarnsen-Node-Service-Tool.exe`
- `jarnsen-node-service-tool.json`
- this README
