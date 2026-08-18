# Heltec Wireless Tracker V1.1 vehicle motion profile

This branch turns the Heltec Wireless Tracker V1.1 into a standalone low-power vehicle tracker using its onboard UC6580 GNSS. Bluetooth remains available so the node can be configured from the Meshtastic app.

## Hardware

- Onboard user/PRG button: GPIO0 (unchanged)
- Passive SW-18010P vibration sensor: GPIO7 to GND
- 100 kOhm pull-up: 3V3 to GPIO7
- 100 nF ceramic capacitor: GPIO7 to GND

GPIO7 is used only as a movement/deep-sleep wake source. Do not configure `device.button_gpio` to GPIO7; keep the normal button on GPIO0.

## Vehicle behavior

- Deep sleep while parked.
- GPIO7 EXT0 wake on vibration.
- Movement is confirmed after 3 falling edges within 3 seconds; isolated bumps return to sleep quickly.
- Once movement is confirmed, the node remains awake while vibration continues.
- After 120 seconds without confirmed movement, the firmware requests a final fresh GNSS position.
- A final GNSS fix is considered fresh for 60 seconds. If no fresh fix exists, the firmware waits up to 30 seconds, then transmits the best available current/cached position.
- Parked timer wake uses `position.position_broadcast_secs` (recommended: 3600 seconds). Because this board has onboard GNSS, it waits up to 45 seconds for a fresh fix before falling back to the last parked position.
- After a position transmit, the node waits 8 seconds before deep sleep.
- GPIO7 stuck LOW for 30 seconds is treated as a sensor/wiring fault. Motion wake is disabled for that sleep cycle so timer/button wake can still work.
- USB power suppresses managed deep sleep for service/debugging.
- Bluetooth is compiled in. Use it for setup/configuration in the Meshtastic app. After setup, Bluetooth may be disabled in Meshtastic settings to reduce awake power consumption; deep sleep itself turns the radio off while parked.

## Recommended Meshtastic settings

- Device role: TRACKER
- Power saving: ON
- GPS mode: ENABLED
- Fixed position: OFF
- Position broadcast interval: 3600 s
- Smart position: ON
- Smart minimum distance: 75 m
- Smart minimum interval: 30 s
- Button GPIO: 0
- LED heartbeat: OFF
- Display timeout: 15 s (optional)
- Bluetooth: ON for initial setup; optional OFF afterwards

With Smart Position enabled, normal Meshtastic PositionModule behavior handles position broadcasts while the vehicle is awake/moving; this profile prevents the normal TRACKER deep-sleep request from putting the node back to sleep during the drive.

## RTC diagnostics

Serial log example:

```text
Tracker V1.1 diag: boots=8 motionWake=4 timerWake=2 buttonWake=1 gpioWake=0 confirmed=3 rejected=1 stuckLow=0 finalFresh=2 finalFallback=0 timerFresh=2 timerFallback=0 noFix=0 blocked=7 sleep=6 lastReason=3
```

The counters survive deep sleep and reset after a true power loss/reset of RTC memory.
