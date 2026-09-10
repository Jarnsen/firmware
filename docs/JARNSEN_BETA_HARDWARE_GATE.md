# JARNSEN-MESH beta hardware gate

This checklist starts only after the final Unified-Core alpha parity gate is green. CI can prove code structure, ordering, contracts, and builds; it cannot prove electrical current, RF behavior, GNSS sensitivity, or physical wake timing.

## Heltec Tracker V1.1

- INA226 LightSleep entry-window: compare the firmware-reported LightSleep estimate with an external current meter. Verify the one-shot value represents the stable sleep plateau and is not dominated by the transition immediately before or after `esp_light_sleep_start()`.
- INA226 DeepSleep entry-window: compare the recovered one-shot estimate after timer wake with an external current meter. Verify the conversion represents the deep-sleep plateau, not shutdown/setup current before sleep or boot current after wake.
- Repeat both tests with INA226 enabled/disabled and with VBUS sense present/missing. Missing VBUS must not invalidate shunt-current accounting; power/energy that require VBUS must remain clearly marked.
- Verify no double counting between awake INA integration and sleep estimates over a measured 30-60 minute run.
- Verify capacity learning does not advance while USB is present, charging is active, charge current is detected, or after a discontinuity/reprobe.
- TAK role: parked LightSleep, radio listening behavior, Userbutton wake-only first press, display 20 s interaction window, motion wake, 60 min park heartbeat, 30 s GNSS search/fallback.
- TAK_TRACKER role: DeepSleep timer wake, button wake, motion wake, fresh/fallback position TX, 8 s post-position settle, re-entry to DeepSleep.
- Verify repeated wake/sleep cycles do not leave GPS, BLE, display, INA226, I2C, or motion GPIO in a stale state.

## Heltec V3

- Establish a normal Meshtastic/Protobuf USB session, then request `JARNSEN_TOOL_FULL` without rebooting.
- Verify exactly one complete `===JARNSEN_DIAG_LOG_BEGIN===` ... payload ... `===JARNSEN_DIAG_LOG_END===` sequence with no protobuf bytes interleaved.
- Immediately reconnect/use normal Meshtastic Protobuf after the export and verify normal USB communication resumes.
- Repeat `JARNSEN_TOOL_HELLO`, `JARNSEN_TOOL_INFO`, `JARNSEN_TOOL_RADIO_INFO`, and profile select; verify no regression.
- Verify 128x64 display content, Userbutton wake and the 20 s display interaction deadline on hardware.
- Verify the proven Meshtastic REPEATER -> TAK_REPEATER legacy mapping does not activate Tracker GNSS/sleep policy.

## Heltec V4 / Wio Tracker L1 / T-Beam / T-Beam Supreme

- Boot and basic mesh join/send/receive.
- USB diagnostic FULL/HELLO where USB serial service is supported by the build.
- Radio profile Standard/Jarnsen 1/Jarnsen 2 selection and reboot persistence.
- Button/display wake behavior on boards with the relevant capability.
- GPS role eligibility only when effective GPS capability exists; no fake GPS/INA226/current/power values on unsupported hardware.
- PMU/ADC battery reporting checked against an external meter where available.

## Drone Repeater - Heltec Tracker V1.1

- Provision through `JARNSEN_TOOL_ROLE_SET drone_repeater`, read back with `JARNSEN_TOOL_ROLE_INFO`, and verify `role=drone_repeater`, `persisted=1`, `allowed=1`, `gps_ready=1`.
- Power-cycle and verify the JARNSEN role survives while the Meshtastic base role remains `ROUTER_LATE` with rebroadcast `ALL`.
- Verify radio + integrated GNSS stay awake continuously on battery and USB; routine PowerFSM LightSleep/DeepSleep must not occur.
- Verify smart position at 25 m and the dynamic 30/10/7/5 s speed tiers, including 15/20/25% channel-utilization braking and immediate TX after a restored fresh fix.
- Verify stationary/ground heartbeat at 30 s when airtime permits.
- Verify Wi-Fi stays off and BLE is off outside the button service window; one GPIO0 press opens BLE, meaningful traffic resets the 120 s idle timer, and the 15 min hard cap closes an idle/stale service.
- Verify display/button operation with the unified five-page UI and battery/USB power transitions; compare diagnostic `DRONE_HEALTH`, `DRONE_POWER_SOURCE`, `DRONE_GPS`, and `DRONE_POSITION_TX` events to observed behavior.

## Drone Repeater - Heltec V4

- Provision through `JARNSEN_TOOL_ROLE_SET drone_repeater` and verify `role=drone_repeater`, `persisted=1`, `allowed=1`.
- Test once without external GNSS: `external_gps_required=1` and `gps_ready=0` must be reported; the node must still run the Drone repeater/radio policy without inventing a GPS fix.
- Attach and configure a supported external GNSS, power-cycle, and verify `gps_ready=1` only after the receiver is physically detected.
- With GNSS ready, repeat the 25 m, 30/10/7/5 s, channel-utilization brake, fresh-fix recovery, and 30 s ground-heartbeat tests used for Tracker V1.1.
- Verify no routine sleep, Wi-Fi off, button-only BLE service, display/button behavior, and clean USB diagnostics on V4 hardware.
- Negative gate: attempt the same Drone role on Heltec V3, Wio Tracker L1, T-Beam, and T-Beam Supreme. `ROLE_SET` must return `reason=unsupported_board`, and a power-cycle must never activate Drone Repeater on those boards.

## Service / transfer stress

- BLE log download with a connected queue: verify idle timeout does not close the service mid-transfer.
- Disconnect/reconnect during and after a transfer; stale queue holds must release.
- LiveView/Web service active while normal idle timeout expires; service must remain alive until the active operation ends.
- WLAN OTA to the inactive firmware partition, successful reboot, and failure/abort path. Do not accept a build that can stop the service while `updateInProgress` is true.
- Repeat sleep attempts while USB export, BLE transfer, LiveView, or OTA is active; no active transfer may be truncated by power policy.

## Position / motion stress

- Moving smart position: 75 m default and 30 s minimum interval.
- Stop moving: after 120 s quiet, use a fresh post-motion fix when available; otherwise wake GNSS up to 30 s and fall back to newest stored position.
- Verify no stale pre-wake fix is reported as fresh after LightSleep/DeepSleep.
- Park heartbeat: verify effective interval and GNSS wake/search/fallback behavior over multiple cycles.
- Motion input: normal pulses, rejected vibration candidate, stuck-low detection and recovery.

## Beta acceptance

Beta hardware validation passes only when logs, external measurements and observed behavior agree. Any hardware-only discrepancy becomes a beta bug; do not weaken the software contracts merely to make the test pass. After this gate, remaining work is bug fixing and release-candidate hardening rather than Unified-Core migration.
