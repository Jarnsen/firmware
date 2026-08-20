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
- shows role, battery percentage and remaining service time;
- allows the Meshtastic phone app to connect for configuration, diagnostics and position setup.

While a real Bluetooth client remains connected, the 120-second idle timer is refreshed. An absolute **15-minute hard cap** prevents an accidental permanent Bluetooth drain.

During service, a **short GPIO0 press** advances between the status page and the position page. The position page explicitly shows `LONG=SAVE POS`, so a deliberate **long press (about 1.2 s)** stores the latest acceptable phone GPS fix immediately.

When the service window ends, Bluetooth and the display are forced OFF and the normal light-sleep repeater power policy is restored.

The GPIO0 service implementation uses a GPIO interrupt / FreeRTOS task notification. Outside an active service window the service task blocks indefinitely instead of polling periodically, so it does not introduce a 100 ms/1 s background wake that would defeat the repeater's light-sleep power saving.

## Phone GPS fixed-position setup

The V3 has no onboard GNSS. During an intentional GPIO0/Bluetooth service session it therefore listens for live position packets from the connected phone without allowing those phone updates to move the repeater immediately. The repeater remains configured as a **fixed-position** node.

A phone fix is accepted for position decisions only when:

- latitude/longitude are present;
- the fix carries a timestamp and is fresh (normally no older than **60 seconds**; a live API packet is accepted when the V3 has not yet obtained a trustworthy epoch itself);
- reported GPS accuracy is present and is **20 m or better**.

The saved repeater position is compared with each acceptable phone fix:

- **0–25 m difference:** do not write anything; the display may show `POSITION OK`.
- **>25 m to 50 m:** show the difference on the position page but do not change the stored position.
- **>50 m:** start automatic relocation confirmation.

Automatic relocation requires **3 good fixes** within **15 seconds**. Confirmation fixes must be at least about **1 second apart** and remain within a **25 m cluster** of each other. This prevents one bad or jumping phone-GPS sample from moving a stationary repeater. Once all three confirmations succeed, the new position is stored automatically.

For the first installation, when no saved repeater position exists yet, automatic relocation is intentionally not used. The position page shows the good phone fix and `LONG=SAVE POS`; the operator performs one deliberate long press to establish the initial fixed location.

A long press on the position page always provides the manual override: if the latest phone fix passes the freshness/accuracy checks, it is stored immediately regardless of whether the difference is 10 m, 40 m or 100 m.

After either a manual or automatic save:

- the position is marked as a fixed/manual location;
- the local node database and configuration are persisted to flash;
- the display confirms `POSITION SAVED` and whether it was `AUTO` or `MANUAL`;
- a position packet is sent immediately on the primary Meshtastic channel when that channel permits position sharing.

If the primary channel has position precision set to zero, the V3 still saves the local fixed position but deliberately does not bypass the Meshtastic privacy setting to transmit it.

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

The repeater has no need for a dedicated GPS module or a motion sensor. Its job is to stay on LoRa, extend coverage, report basic infrastructure health, consume as little CPU/client-radio power as possible, and remain locally serviceable without USB.

This document is included in the dedicated hardware workflow path so changes to the repeater profile always trigger a Heltec V3 target build.
