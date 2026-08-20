# Tracker V1.1 custom TAK roles

## Common behavior

- GPIO0 is exclusively owned by the local service UI; stock Meshtastic button handling is disabled.
- The normal Meshtastic boot logo is allowed to complete. After `STOP_BOOT_SCREEN`, stock carousel frames are suppressed.
- GPIO0 opens Bluetooth and the custom full-screen menu. Display window: 20 s (10 s at <=20% battery).
- Service idle timeout: 120 s; hard cap: 15 min.
- Only physical GPIO0 use or real BLE PHONE->RADIO writes refresh the service idle timer. A merely connected/background phone does not.
- Bluetooth is deinitialized outside the service window.
- Pairing PIN is rendered as an overlay on the custom frame.
- Short GPIO0 press advances pages; long press (~1.2 s) changes supported settings.
- SW-18010P motion defaults to NORMAL = 2 falling edges within 3 s. The selected motion preset is used by both roles.
- Smart Position defaults remain 75 m minimum distance and 30 s minimum interval; parked reporting defaults to 60 min with deterministic 0..180 s desynchronization for hourly-or-longer intervals.

## TAK

- Onboard GNSS tracks while vehicle motion is active.
- 120 s motion quiet triggers a final fresh-position attempt (up to 30 s), then returns to light sleep.
- Parked mode uses light sleep so LoRa remains available for incoming mesh traffic.
- Periodic autonomous position heartbeat uses the configured parked interval.

## TAK_TRACKER

- Onboard GNSS tracks while vehicle motion is active.
- 120 s motion quiet triggers a final fresh-position attempt (up to 30 s), then deep sleep after the post-position guard interval.
- GPIO7/SW-18010P wakes the tracker from deep sleep; timer wake performs the parked position report.
- Parked GNSS acquisition is adaptive (learned TTFF, low-battery limits, periodic full retries).
- USB/serial prevents managed deep sleep but does not suppress GPIO7 motion processing, so bench diagnostics match battery operation.
