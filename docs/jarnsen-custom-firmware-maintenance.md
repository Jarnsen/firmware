# Jarnsen custom firmware - Meshtastic update strategy

This repository keeps the field-specific firmware in two long-lived branches:

- `heltec-tracker-v11-vehicle-motion-wake` - Heltec Wireless Tracker V1.1 with `TAK` and `TAK_TRACKER` policies.
- `heltec-v3-repeater-light-sleep` - Heltec WiFi LoRa 32 V3 infrastructure profile using `ROUTER_LATE`.

The goal is to consume future Meshtastic releases without rewriting the custom firmware.

## Design rule

Custom behavior belongs in dedicated files whenever possible.

For the Tracker V1.1, most project logic lives under `src/vehicle/`. The remaining Meshtastic-core changes are intentionally limited and guarded:

1. `src/PowerFSM.cpp` - narrow phone-contact hook for the vehicle service/sleep policy.
2. `src/modules/PositionModule.h` - runtime refresh of the Smart Position minimum interval.
3. `src/platform/extra_variants/heltec_wireless_tracker/variant.cpp` - starts the Tracker V1.1 custom policies.
4. `variants/esp32s3/heltec_wireless_tracker/platformio.ini` - tracker-specific linker/build option.
5. `variants/esp32s3/heltec_wireless_tracker/variant.h` - Tracker V1.1 hardware definitions.

For the V3 repeater profile, the expected core touchpoints are limited to:

1. `src/platform/extra_variants/heltec_v3/variant.cpp` - infrastructure power/telemetry policy.
2. `variants/esp32s3/heltec_v3/variant.h` - V3 profile build definition.

`tools/jarnsen/check_custom_core_touchpoints.py` fails the compatibility workflow if a custom branch starts modifying additional Meshtastic core files without that change being deliberately added to the allowlist.

## Automatic upstream compatibility test

`.github/workflows/jarnsen-custom-firmware-compatibility.yml` tests both custom branches against the latest official `meshtastic/firmware` `develop` branch.

It runs:

- whenever this fork's `develop` branch changes;
- every Monday at 04:17 UTC;
- manually through GitHub Actions with `workflow_dispatch`.

For each custom branch the workflow:

1. checks out the custom branch;
2. fetches the latest official Meshtastic `develop` branch directly from `https://github.com/meshtastic/firmware.git`;
3. verifies the custom core-touchpoint allowlist;
4. performs a temporary, non-persistent test merge of upstream `develop`;
5. reports merge conflicts immediately;
6. builds the real hardware target with PlatformIO.

The test does **not** modify either custom branch. It only answers: "Would the current custom firmware still merge and compile against today's Meshtastic develop?"

## Normal update procedure

When a new Meshtastic version is desired:

1. Check the latest `Jarnsen Custom Firmware Upstream Compatibility` workflow.
2. If both jobs are green, merge/rebase the desired upstream Meshtastic commit into each custom branch.
3. Run the branch-specific hardware workflows:
   - `Build Heltec Tracker V1.1 Vehicle Motion Wake`
   - `Build Heltec V3 Repeater Light Sleep`
4. Flash the generated `.update.bin` when an existing Meshtastic installation and configuration should be preserved.
5. Use `.factory.bin` only for a fresh/full installation or deliberate clean reset.
6. Perform a short hardware smoke test before updating the whole fleet.

A normal upstream update should therefore be: **upstream merge -> green hardware builds -> update.bin -> field test**.

## If compatibility turns red

### Merge conflict

Resolve only the files named by the workflow. Start with the small guarded core-touchpoint list above. Custom `src/vehicle/` files should normally merge unchanged.

### Compile failure without merge conflict

This usually means Meshtastic changed an internal API used by the custom code. Fix the adapter/call site rather than copying new Meshtastic internals into the custom branch.

### New core file appears in the touchpoint guard

Do not simply expand the allowlist. First ask whether the behavior can live in `src/vehicle/` or the appropriate variant file. Add a new core touchpoint only if there is no clean hook available, and document the reason here.

## Release discipline

Keep each hardware workflow green before fleet deployment. The Tracker build embeds the project version and short Git SHA so a unit can identify which custom build it is running from the local service menu.

The long-term target is to keep upstream maintenance boring: a very small core patch surface, custom policy files that remain isolated, and automatic hardware compilation against current Meshtastic before any fleet update.
