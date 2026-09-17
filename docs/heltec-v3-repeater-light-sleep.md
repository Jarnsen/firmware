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
- enables Bluetooth immediately;
- starts a **20-second connection window**;
- shows role, battery percentage and service information;
- allows the Meshtastic phone app to connect for configuration, diagnostics and position setup.

The BLE lifetime is connection-driven:

- while GPIO0 is held, Bluetooth remains available;
- after the button is released, a 20-second tail remains;
- once a real BLE client connects, Bluetooth remains available for as long as that connection exists;
- after BLE disconnects, a fresh 20-second reconnect tail starts;
- a new GPIO0 press restarts the 20-second tail;
- the OLED still turns off independently after roughly 20 seconds unless local UI activity reopens it.

There is no normal 120-second BLE inactivity window and no 15-minute cutoff for an actively connected phone. Outside the button/connection/tail conditions, Bluetooth is parked again and the V3 returns to its unattended repeater policy.

During service, a short GPIO0 press advances between local pages. The position page keeps a deliberate long-press save action as a manual override.

The GPIO0 service implementation uses GPIO wake plus task notification. Outside an active service window there is no permanent 100 ms button poll. GPIO0 still wakes the device immediately.

## Battery capacity learning

With an INA226 R100 in the battery-to-node load path, the V3 integrates the node's discharge current and learns the usable 1S battery capacity after a sufficiently large discharge window. `Power Statistics` shows learned capacity, estimated remaining mAh, confidence and learning cycles. The normal service status page shows the learned capacity in Ah next to the battery percentage. Until the measurement is reliable it explicitly shows `LEARN`; without INA226 it reports that the sensor is required instead of inventing a value from voltage alone.

Capacity learning restarts its sample window while USB/charging or reverse current is detected, so later solar input is not misinterpreted as node consumption. For a future solar installation the INA226 must remain in the node load branch if the goal is to measure node consumption; a separate sensor is needed for independent solar-charge energy.

## Phone GPS and repeater position

The V3 has no onboard GNSS. Its unattended location is therefore stored as a **fixed position**, while a connected phone can temporarily provide fresh GPS fixes during an intentional GPIO0/BLE service session.

The custom firmware captures the authorized phone GPS payload before the normal fixed-position handling can discard or rewrite it. A phone fix is accepted for the custom position manager only when:

- latitude/longitude are present;
- the fix has a timestamp and is no older than **60 seconds**;
- reported GPS accuracy is present and is **20 m or better**.

### Repeater moved to a new stationary site

The saved fixed position is compared with good phone fixes. Changes up to about 50 m are ignored for automatic relocation.

When the phone is more than 50 m from the saved repeater position and the service session remains spatially stable, the manager forms a stationary cluster. Four accepted fixes must remain within roughly 35 m, span at least 25 seconds and complete inside a 120-second confirmation window. After confirmation the new location is written once as the fixed repeater position and broadcast to the mesh.

The original short-window auto-save path is disabled for this build so it cannot fight the mobile-session logic.

### Temporary vehicle operation

If the good phone fixes move far enough to break the stationary cluster, that BLE service session is classified as **mobile**. From that point until the service session ends:

- phone GPS is used as a live position source;
- live position packets use the configured Smart Position thresholds;
- the intended defaults are **75 m minimum distance** and **30 s minimum interval**;
- the moving phone position is **not** written repeatedly to flash;
- the stored fixed repeater location remains unchanged.

A mobile session is deliberately not converted back into an automatic fixed-location save just because the vehicle stops at a traffic light or in a queue. If the V3 is actually being installed at the destination, disconnect/reopen the service session while it is stationary, or use the position page's long-press save override.

This gives two distinct behaviors without a motion sensor: a stationary relocation becomes the new persistent repeater position, while a drive uses temporary live phone GPS without repeated flash writes.

After a manual or automatic fixed-position save:

- the position is marked as a fixed/manual location;
- the local node database and configuration are persisted to flash;
- a position packet is sent immediately on the primary Meshtastic channel when that channel permits position sharing.

If the primary channel has position precision set to zero, the V3 still keeps its local fixed position but deliberately does not bypass the Meshtastic privacy setting to transmit it.

## Recommended Meshtastic app settings

For this profile use:

- Device role: `ROUTER_LATE` (recommended).
- Position → **Fixed Position: ON**.
- Position → **Smart Position: ON**.
- Smart minimum distance: **75 m**.
- Smart minimum interval: **30 s**.
- Normal position broadcast interval: about **3600 s** for the stationary repeater.
- Device GPS/GNSS: disabled / not present on the Heltec V3.
- App option **Share phone location with mesh: ON** while using position setup or vehicle mode.
- Give the Meshtastic app precise location permission; for vehicle use with the phone screen off, allow background location and avoid aggressive battery restriction.
- Primary channel position sharing/precision must be enabled if the V3 should actually transmit its location.

`Fixed Position` stays ON even for temporary vehicle use. The firmware captures the live phone fix separately, broadcasts temporary mobile fixes when appropriate, and only replaces the stored fixed position after a stationary relocation confirmation or a deliberate manual save.

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
- Position fixed: ON
- Smart Position: ON, 75 m / 30 s
- Bluetooth: enabled in saved configuration; the profile owns actual BLE radio on/off timing
- Wi-Fi: any saved value is overridden OFF while this profile is active
- Power saving: any saved value is overridden ON while this profile is active

The repeater has no need for a dedicated GPS module or a motion sensor. Its job is to stay on LoRa, extend coverage, report basic infrastructure health, consume as little CPU/client-radio power as possible, and remain locally serviceable without USB.

This document is included in the dedicated hardware workflow path so changes to the repeater profile always trigger a Heltec V3 target build.
