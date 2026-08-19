# Heltec V3 repeater / infrastructure profile

This branch turns the Heltec WiFi LoRa 32 V3 into a low-power infrastructure node for field exercises.

## Wiring

Full illustrated wiring guide: [`docs/heltec-v3-repeater-wiring.md`](heltec-v3-repeater-wiring.md)

The guide includes the official Heltec V3 pin map and the minimal repeater connections. **No SW-18010P motion sensor and no GPIO7 wiring are used on the V3 repeater.** The normal battery-powered installation only needs the 1S lithium battery connection and the 868 MHz LoRa antenna.

## Recommended role

Use `ROUTER_LATE` for normal deployments. Current Meshtastic marks the older `REPEATER` role deprecated because it can create holes in the rebroadcast chain. The firmware still supports `REPEATER` for deliberate legacy use.

Functionally this V3 is the repeater/infrastructure element in the two-hardware, three-role architecture:

- Wireless Tracker V1.1 + `TAK` = leadership element with onboard GNSS and ATAK phone on demand.
- Wireless Tracker V1.1 + `TAK_TRACKER` = autonomous Kfz tracker with SW-18010P parked deep sleep.
- Heltec V3 + `ROUTER_LATE` (recommended) = always-listening LoRa repeater using ESP32 light sleep.

## Power behavior

When the saved role is `ROUTER_LATE` or `REPEATER`, the V3-specific late-init policy applies these runtime settings before PowerFSM starts:

- Power saving ON.
- Bluetooth OFF.
- Wi-Fi OFF.
- Display OFF, with screen timeout reduced to 1 s.
- Minimum wake window 1 s.
- Light-sleep service timer 3600 s.
- No custom deep sleep.

The SX1262 remains available as the LoRa wake source during ESP32 light sleep. A received LoRa interrupt wakes the ESP32-S3, Meshtastic processes/rebroadcasts the packet, and PowerFSM returns to light sleep.

For the legacy `REPEATER` role only, rebroadcast mode is forced to `ALL_SKIP_DECODING` for minimum processing overhead. `ROUTER_LATE` keeps its normal role-specific rebroadcast behavior.

## Required saved configuration

Recommended:

- Device role: `ROUTER_LATE`
- Region: `EU_868`
- Same LoRa preset/channel parameters as the rest of the exercise mesh
- Bluetooth: any saved value is overridden OFF while this profile is active
- Wi-Fi: any saved value is overridden OFF while this profile is active
- Power saving: any saved value is overridden ON while this profile is active

The repeater has no need for GPS or a motion sensor. Its job is to stay on LoRa, extend coverage, and consume as little CPU/client-radio power as possible.

This document is included in the dedicated hardware workflow path so changes to the repeater profile always trigger a Heltec V3 target build.