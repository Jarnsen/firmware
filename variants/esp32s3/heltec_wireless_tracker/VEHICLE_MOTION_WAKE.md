# Heltec Wireless Tracker V1.1 vehicle motion profile

This branch turns the Heltec Wireless Tracker V1.1 into a standalone low-power vehicle tracker using its onboard UC6580 GNSS. Bluetooth remains available for motion/service use without being needed for the hourly parked position report.

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
- Bluetooth is made available when movement is confirmed.
- Real Meshtastic app traffic refreshes a 60-second BLE activity hold. A passive connection alone does not keep the tracker awake indefinitely.
- A parked timer wake does not need Bluetooth; BLE is kept off during that timer-only cycle.
- After 120 seconds without confirmed movement, the firmware requests a final fresh GNSS position.
- A final GNSS fix is considered fresh for 60 seconds. If no fresh fix exists, the firmware waits up to 30 seconds, then transmits the best available current/cached position.
- After a position transmit, the node waits 8 seconds before deep sleep.
- GPIO7 stuck LOW for 30 seconds is treated as a sensor/wiring fault. Motion wake is disabled for that sleep cycle so timer/button wake can still work.
- USB power suppresses managed deep sleep for service/debugging.

## User button / service mode

- A deliberate GPIO0 user-button wake opens a two-minute Bluetooth service window.
- The service policy periodically keeps PowerFSM awake so the node does not fall into light sleep halfway through the requested service period.
- The display is normally OFF during movement, hourly timer wakes and ordinary tracker operation.
- A user-button press turns the display on only for a short diagnostic window: normally 20 seconds, or 10 seconds when the battery is at or below 20%.
- The diagnostic banner shows battery percentage, position/GNSS state, wake reason and motion-input state.
- Pressing GPIO0 again restarts the service and display windows.

## Adaptive parked GNSS search

The hourly position report remains enabled, but repeated GNSS failures no longer force a full 45-second search every hour:

- First three consecutive unsuccessful parked timer cycles: up to 45 seconds each.
- After three consecutive failures: normally 12-second GNSS attempts.
- Every sixth parked timer wake: a full 45-second retry so outdoor reception is rediscovered automatically.
- At or below 20% battery: timer-wake GNSS search is limited to 10 seconds.
- A fresh fix resets the consecutive-failure counter.
- If no fresh fix is acquired, the best available cached parked position is still transmitted, so the hourly LoRa report is not removed.

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
- Bluetooth: ON
- Bluetooth wait: 60 s

With Smart Position enabled, normal Meshtastic PositionModule behavior handles position broadcasts while the vehicle is awake/moving; this profile prevents ordinary TRACKER deep-sleep requests from putting the node back to sleep during the drive.

## RTC diagnostics

The existing vehicle counters survive deep sleep and record boots, motion/timer/button wakes, confirmed and rejected motion events, BLE activity, GNSS fresh/fallback sends and sleep decisions. The adaptive GNSS code additionally logs the parked timer count, consecutive no-fix count and selected GPS search duration.