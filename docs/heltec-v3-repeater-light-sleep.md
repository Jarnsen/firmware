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

When the saved role is `ROUTER_LATE` or `REPEATER`, the V3-specific late-init policy applies these runtime settings:

- Power saving ON.
- Bluetooth radio OFF during unattended operation; BLE stack remains available for GPIO0 service.
- Wi-Fi OFF.
- Display OFF, with screen timeout reduced to 1 s outside service.
- Minimum wake window 1 s.
- Light-sleep service timer 3600 s.
- No custom deep sleep.

The SX1262 remains available as the LoRa wake source during ESP32 light sleep. A received LoRa interrupt wakes the ESP32-S3, Meshtastic processes/rebroadcasts the packet, and PowerFSM returns to light sleep.

For the legacy `REPEATER` role only, rebroadcast mode is forced to `ALL_SKIP_DECODING` for minimum processing overhead. `ROUTER_LATE` keeps its normal role-specific rebroadcast behavior.

## GPIO0 local service mode

The normal onboard GPIO0 button opens a temporary maintenance window without changing the repeater's normal LoRa duty.

A deliberate GPIO0 press:

- wakes the ESP32-S3 from light sleep;
- turns the display on for approximately **20 seconds**;
- enables Bluetooth for a **120-second idle service window**;
- shows role, battery percentage, remaining service time and uptime;
- allows the Meshtastic phone app to connect for configuration/diagnostics.

While a real Bluetooth client remains connected, the 120-second idle timer is refreshed. An absolute **15-minute hard cap** prevents an accidental permanent Bluetooth drain. Pressing GPIO0 again during service refreshes the display and idle window.

When the service window ends, Bluetooth and the display are forced OFF and the normal light-sleep repeater power policy is restored.

The GPIO0 service implementation uses a GPIO interrupt / FreeRTOS task notification. Outside an active service window the service task blocks indefinitely instead of polling periodically, so it does not introduce a 100 ms/1 s background wake that would defeat the repeater's light-sleep power saving.

## Infrastructure health telemetry

The profile explicitly enables Meshtastic device telemetry for the repeater. The reporting interval is deterministically spread by Node ID across approximately **55 to 60 minutes**, so two infrastructure nodes that are powered up together do not habitually transmit their health packets at exactly the same time.

The standard device-telemetry packet provides the fields that are directly useful for unattended infrastructure monitoring:

- battery percentage;
- battery voltage when the board has a valid battery reading;
- uptime;
- LoRa channel utilization;
- transmit airtime utilization.

The ESP32 reset reason is also written to the serial/debug log at boot. It is intentionally not encoded into a non-standard telemetry field, so normal Meshtastic clients remain fully compatible.

This health traffic is background telemetry and does not change the repeater's primary duty: LoRa reception and rebroadcast remain immediately wake-capable while client radios and the display stay off.

## Required saved configuration

Recommended:

- Device role: `ROUTER_LATE`
- Region: `EU_868`
- Same LoRa preset/channel parameters as the rest of the exercise mesh
- Bluetooth: the profile keeps the BLE stack available but forces the radio OFF outside GPIO0 service
- Wi-Fi: any saved value is overridden OFF while this profile is active
- Power saving: any saved value is overridden ON while this profile is active

The repeater has no need for GPS or a motion sensor. Its job is to stay on LoRa, extend coverage, report basic infrastructure health, consume as little CPU/client-radio power as possible, and remain locally serviceable without USB.

This document is included in the dedicated hardware workflow path so changes to the repeater profile always trigger a Heltec V3 target build.
