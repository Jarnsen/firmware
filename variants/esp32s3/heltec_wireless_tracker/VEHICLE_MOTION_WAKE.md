# Heltec Wireless Tracker V1.1 vehicle motion profile

This branch turns the Heltec Wireless Tracker V1.1 into a standalone low-power vehicle tracker using its onboard UC6580 GNSS. The intended and required field role for the custom parked vehicle profile is `TAK_TRACKER`.

## Hardware and service menu

Full illustrated wiring guide: [`docs/heltec-tracker-v11-wiring.md`](../../../docs/heltec-tracker-v11-wiring.md)

GPIO0 Bluetooth/service/settings guide: [`docs/heltec-tracker-v11-service-menu.md`](../../../docs/heltec-tracker-v11-service-menu.md)

- Onboard user/PRG button: GPIO0 (unchanged)
- Passive SW-18010P vibration sensor: GPIO7 to GND
- 100 kOhm pull-up: 3V3 to GPIO7
- 100 nF ceramic capacitor: GPIO7 to GND

GPIO7 is used only as a movement/deep-sleep wake source. Do not configure `device.button_gpio` to GPIO7; keep the normal button on GPIO0.

## Vehicle behavior

- Deep sleep while parked.
- GPIO7 EXT0 wake on vibration.
- Default `NORMAL` movement confirmation is **3 falling edges within 3 seconds**; isolated bumps return to sleep quickly.
- Motion sensitivity is adjustable from the GPIO0 service menu: `VERY SENS` 2/3 s, `SENSITIVE` 3/4 s, `NORMAL` 3/3 s, `ROBUST` 4/3 s.
- Once movement is confirmed, the node remains awake while vibration continues.
- **Movement does not enable Bluetooth.** Bluetooth stays OFF unless GPIO0 deliberately opens service.
- A parked timer wake keeps Bluetooth OFF.
- After 120 seconds without confirmed movement, the firmware requests a final fresh GNSS position.
- A final GNSS fix is considered fresh for 60 seconds. If no fresh fix exists, the firmware waits up to 30 seconds, then transmits the best available current/cached position.
- After a position transmit, the node waits 8 seconds before deep sleep.
- GPIO7 stuck LOW for 30 seconds is treated as a sensor/wiring fault. Motion wake is disabled for that sleep cycle so timer/button wake can still work.
- USB power suppresses managed deep sleep for service/debugging.

## GPIO0 Bluetooth / settings service

Bluetooth must remain ON in the **saved Meshtastic configuration** so the BLE stack exists after boot. Operationally the firmware forces BLE OFF outside intentional service.

- A deliberate GPIO0 press opens a **120-second Bluetooth/settings window**.
- During service the custom parked power-saving state is temporarily suspended so the node cannot deep-sleep in the middle of configuration work.
- First press opens STATUS and Bluetooth.
- Further short presses advance through MOTION, MIN DISTANCE, MIN INTERVAL and PARK UPDATE.
- A long press of about 1.2 s cycles the value on an editable page.
- The display stays on for up to 20 seconds after an interaction, or 10 seconds at <=20% battery.
- At the end of the 120-second service window Bluetooth is explicitly switched OFF, the display is switched OFF and autonomous power saving is restored.

Normal Meshtastic parameters such as channel, PSK, LoRa region, node name and TAK configuration can still be changed through the Meshtastic app during the Bluetooth service window.

## Local field presets

The local Tracker V1.1 settings are persisted in ESP32 NVS and survive deep sleep/reboots.

| Setting | Choices | Default |
|---|---|---|
| Motion sensitivity | VERY SENS / SENSITIVE / NORMAL / ROBUST | NORMAL = 3 pulses / 3 s |
| Smart minimum distance | 50 / 75 / 100 / 150 m | 75 m |
| Smart minimum interval | 30 / 45 / 60 / 90 s | 30 s |
| Park update | 30 / 60 / 120 / 240 min | 60 min |

The Smart Position minimum interval is refreshed live in PositionModule when changed; no reboot is required.

## Adaptive parked GNSS search

The parked position report remains enabled according to the selected PARK UPDATE interval. Repeated GNSS failures do not force a full 45-second search every cycle:

- First three consecutive unsuccessful parked timer cycles: up to 45 seconds each.
- After three consecutive failures: normally 12-second GNSS attempts.
- Every sixth parked timer wake: a full 45-second retry so outdoor reception is rediscovered automatically.
- At or below 20% battery: timer-wake GNSS search is limited to 10 seconds.
- A fresh fix resets the consecutive-failure counter.
- If no fresh fix is acquired, the best available cached parked position is still transmitted.

## Recommended Meshtastic settings

- Device role: `TAK_TRACKER`
- Bluetooth: **ON in saved config** (runtime BLE is button-only)
- GPS mode: ENABLED
- Fixed position: OFF
- Button GPIO: 0
- LED heartbeat: OFF

Power saving, Wi-Fi, GNSS and the local Smart Position/Park presets are enforced by the custom runtime policy.

## Role split in this branch

- `TAK_TRACKER`: Kfz tracker; custom SW-18010P parked deep sleep, configurable parked report and adaptive GNSS search.
- `TAK`: leadership element; does not enter the custom parked deep-sleep profile. It uses the dedicated TAK leadership light-sleep policy documented in `TAK_LEADER.md`.

## RTC diagnostics

The vehicle counters survive deep sleep and record boots, motion/timer/button wakes, confirmed and rejected motion events, BLE activity, GNSS fresh/fallback sends and sleep decisions. The adaptive GNSS code additionally logs the parked timer count, consecutive no-fix count and selected GPS search duration.
