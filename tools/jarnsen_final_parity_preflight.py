#!/usr/bin/env python3
"""Final Unified-Core parity/lifecycle contracts before the beta hardware gate.

This is intentionally a static engineering gate. It verifies ordering and ownership
invariants that CI can prove, and keeps hardware-only claims (actual current draw,
RF/GNSS sensitivity, wake electrical behavior) out of the software PASS result.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


class AuditFailure(RuntimeError):
    pass


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise AuditFailure(f"required file missing: {rel}")
    return path.read_text(encoding="utf-8")


def require(text: str, needle: str, message: str) -> None:
    if needle not in text:
        raise AuditFailure(message)


def forbid(text: str, needle: str, message: str) -> None:
    if needle in text:
        raise AuditFailure(message)


def require_order(text: str, needles: tuple[str, ...], label: str) -> None:
    pos = -1
    for needle in needles:
        next_pos = text.find(needle, pos + 1)
        if next_pos < 0:
            raise AuditFailure(f"{label}: missing {needle!r}")
        if next_pos <= pos:
            raise AuditFailure(f"{label}: ordering changed around {needle!r}")
        pos = next_pos


def main() -> int:
    roles = read("src/jarnsen/core/roles/JarnsenDeviceRole.h")
    caps = read("src/jarnsen/core/capabilities/JarnsenCapabilities.h")
    hardware = read("src/jarnsen/hardware/JarnsenHardwareProfiles.h")
    bridge = read("src/jarnsen/adapters/JarnsenLegacyStatusBridge.cpp")
    role_store = read("src/jarnsen/core/roles/JarnsenRolePersistence.cpp")
    drone_runtime = read("src/jarnsen/core/runtime/JarnsenDroneRepeaterPolicy.cpp")
    tak_runtime = read("src/jarnsen/core/runtime/JarnsenTakRepeaterPolicy.cpp")
    common = read("src/vehicle/TrackerCommonPolicy.cpp")
    power_fsm = read("src/PowerFSM.cpp")
    power = read("src/vehicle/TrackerPowerMonitor.cpp")
    power_header = read("src/vehicle/TrackerPowerMonitor.h")
    settings = read("src/vehicle/TrackerServiceSettings.cpp")
    sleep = read("src/sleep.cpp")
    serial = read("src/SerialConsole.cpp")
    diag = read("src/jarnsen/core/service/JarnsenDiagnosticLog.cpp")
    web = read("src/mesh/http/JarnsenServiceWeb.cpp")
    web_header = read("src/mesh/http/JarnsenServiceWeb.h")
    nimble = read("src/nimble/NimbleBluetooth.cpp")
    button = read("src/input/ButtonThread.cpp")
    input_broker = read("src/input/InputBroker.cpp")
    display_runtime = read("src/jarnsen/adapters/JarnsenDisplayRuntime.cpp")
    state_cache = read("src/jarnsen/core/mesh/JarnsenNodeStateCache.h")
    state_cache_impl = read("src/jarnsen/core/mesh/JarnsenNodeStateCache.cpp")
    state_sync = read("src/jarnsen/core/mesh/JarnsenNodeStateSync.cpp")
    runtime_policy = read("src/jarnsen/core/runtime/JarnsenRuntimePolicy.cpp")
    pin_renderer = read("src/jarnsen/core/display/JarnsenPinRenderer.h")
    tracker_pin_patch = read("tools/patch_jarnsen_tracker_full_lock_common_v5.py")
    unified_pin_patch = read("tools/patch_jarnsen_unified_full_lock_ui.py")
    beta_gate = read("docs/JARNSEN_BETA_HARDWARE_GATE.md")
    unified_daily = read(".buildkite/run-unified-build-daily.sh")

    # Tracker V1.1 is the interaction reference wherever hardware permits.
    require(button, "JARNSEN_SINGLE_EVENT_FAST_POLL_V1",
            "Shared one-button polling is not using the conservative fast path")
    require(button, "JARNSEN_RELEASE_OWNS_SHORT_V2",
            "Shared one-button short press is not owned by stable physical release")
    require(button, '"event=onebutton_short suppressed=1 authority=stable_release"',
            "Shared one-button path can still emit a delayed duplicate click")
    require(button, "JARNSEN_IRQ_RELEASE_TIMESTAMP_V1",
            "Shared one-button release debounce is not anchored to the physical IRQ edge")
    require(input_broker, "notePhysicalEdgeFromInterrupt();",
            "Userbutton IRQ path no longer captures the physical release timestamp")
    require(display_runtime, "JARNSEN_MENU_SELECTED_MEDIUM_V1",
            "Selected menu row can regress to the same small font as secondary rows")
    require(display_runtime, 'static const char *items[] = {"BLUETOOTH", "WLAN", "LOG", "ZURUECK"};',
            "Service menu labels are no longer the compact WLAN/LOG form")
    require(input_broker, "JARNSEN_FULL_LOCK_OWNS_LONG_HOLD_V1",
            "JARNSEN one-button long holds are not reserved for Full Lock")
    require(input_broker, "userConfig.longLongPress = INPUT_BROKER_NONE;",
            "JARNSEN screened one-button path can still shut down on an aborted Full Lock hold")
    require(pin_renderer, "drawReferenceSixDigitPin", "Shared V1.1 PIN renderer missing")
    require(display_runtime, "drawReferenceSixDigitPin", "Shared display menu PIN does not use V1.1 renderer")
    require(tracker_pin_patch, "drawReferenceSixDigitPin", "Tracker PIN is not using the common reference renderer")
    require(unified_pin_patch, "drawReferenceSixDigitPin", "Non-Tracker Full Lock PIN is not using the common reference renderer")
    require(display_runtime, "parkSharedBluetoothForWlan();", "Shared WLAN start bypasses V1.1 BLE handover ordering")
    require(display_runtime, "restoreSharedBluetoothAfterWlan();", "Shared WLAN close/failure does not restore BLE")
    require(display_runtime, "JARNSEN_SHARED_WLAN_DEINIT_V1",
            "Shared ESP32 WLAN handover no longer fully releases NimBLE")
    require(tak_runtime, "JARNSEN_WLAN_OWNS_ESP32_RADIO_V1",
            "TAK Repeater can reinitialize NimBLE while ServiceWeb owns ESP32 radio")
    require(tak_runtime, "if (jarnsenServiceWebActive())",
            "TAK Repeater BLE start no longer respects active WLAN")
    require(tak_runtime, "JARNSEN_SERVICE_POST_PUMP_CLOCK_V1",
            "Service idle clock can regress across Web pump activity")
    require(tak_runtime, "else if (idle && !webActive)",
            "Active ServiceWeb can still be closed by BLE-service idle timeout")
    require(display_runtime, "JARNSEN_V3_WLAN_EXIT_REBOOT_V1",
            "Heltec V3 can attempt unsafe same-boot NimBLE restart after WLAN")
    require(display_runtime, "nimbleBluetooth->deinit();",
            "Heltec V3 WLAN can regress to suspend-only startup")
    require(display_runtime, "bond_store=preserved",
            "Shared WLAN handover no longer preserves documented BLE bond storage")
    require(display_runtime, "delay(150);",
            "Shared WLAN handover lacks controller teardown settle time")
    require(display_runtime, "nimbleBluetooth->resume();", "Shared WLAN handover cannot restore BLE after WLAN")

    # Distributed JARNSEN state sync: old cache data must never be made young.
    require(state_cache, "JARNSEN_NODE_STATE_CACHE_CAPACITY = 128U",
            "Node-state cache capacity is no longer 128")
    require(state_cache_impl, "NodeStateCache::snapshotPage(",
            "Expanded cache no longer supports paged snapshots")
    require(state_sync, "JARNSEN_STATE_SYNC_PAGED_CACHE_V1",
            "Node-state sync no longer pages the expanded cache")
    require(state_sync, "JARNSEN_STATE_SYNC_SIGNATURE_HELLO_V1",
            "Cache-signature HELLO optimization is missing")
    require(state_sync, "JARNSEN_STATE_SYNC_HASH_GATE_V1",
            "Unchanged caches can again trigger hourly full digests")
    require(state_sync, "FULL_RECONCILE_INTERVAL_MS = 6UL * 60UL * 60UL * 1000UL",
            "Six-hour full cache verification fallback is missing")
    require(state_sync, "MAX_PEERS = JARNSEN_NODE_STATE_CACHE_CAPACITY",
            "State sync peer history no longer scales with the 128-node cache")
    require(state_sync, "size < HELLO_META_SIZE || payload[8] != HELLO_META_VERSION",
            "New state sync is no longer backward-compatible with legacy HELLO packets")
    require(state_cache, "JARNSEN_TAK_STATIONARY_CACHE_SECS = 2U * 60U * 60U",
            "Stationary TAK/TAK_TRACKER cache lifetime is no longer two hours")
    require(state_cache_impl, "candidate.sourceEpoch < previous->sourceEpoch",
            "Cache can overwrite a newer source position with an older one")
    require(state_cache_impl, "previous->origin == NodeStateOrigin::DIRECT && candidate.origin == NodeStateOrigin::SYNC",
            "DIRECT no longer wins a same-timestamp conflict over SYNC")
    require(state_sync, "SyncMessage::DIGEST", "State-sync digest protocol missing")
    require(state_sync, "SyncMessage::REQUEST", "State-sync request protocol missing")
    require(state_sync, "SyncMessage::RECORD", "State-sync record protocol missing")
    require(state_sync, "SyncMessage::RECEIPT_REQUEST", "State-sync FINAL_POS receipt request missing")
    require(state_sync, "SyncMessage::RECEIPT", "State-sync FINAL_POS receipt response missing")
    require(state_sync, "pendingDigestNode_ = 0U;", "Responder election cancellation missing")
    require(state_sync, "record.expiresEpoch", "State sync no longer transports original expiry")
    require(state_sync, "position.timestamp ? position.timestamp : (position.time ? position.time : now)",
            "State cache no longer prefers the actual GPS-solution timestamp")
    require(state_sync, "atakSpeedToNativeCentiKmh",
            "TAK/native speed-unit conversion is missing from state replay")
    require(runtime_policy, "nodeStateSyncInit();", "State sync is not installed for configured JARNSEN roles")

    # ------------------------------------------------------------------
    # Role/capability parity: role intent and hardware ability stay separate.
    # ------------------------------------------------------------------
    for role in ("TAK", "TAK_TRACKER", "TAK_REPEATER", "DRONE_REPEATER"):
        require(roles, role, f"Core role missing: {role}")
    require(roles, "return role == DeviceRole::TAK_TRACKER;", "Tracker role predicate changed")
    require(roles, "return role == DeviceRole::TAK_REPEATER || role == DeviceRole::DRONE_REPEATER;",
            "Repeater family predicate changed")
    require(roles, "return {true, false, false, false, false, false, false, false, false, false, false};",
            "GPS requirement for GPS-bound roles changed")
    require(caps, "board.internalGps || (board.supportsExternalGps && peripherals.externalGps)",
            "Effective GPS capability no longer separates built-in and external GPS")
    require(caps, "board.supportsIna226 && peripherals.ina226", "INA226 capability is no longer opt-in by board and peripheral")

    # Board role availability is deliberate, not inferred from peripherals.
    require(hardware, "{true, true, true, true},", "Tracker V1.1 role availability changed")
    require(hardware, "HardwareKind::BOARD_HELTEC_V3", "Heltec V3 hardware profile missing")
    require(hardware, "HardwareKind::BOARD_HELTEC_V4", "Heltec V4 hardware profile missing")
    require(hardware, "HardwareKind::BOARD_SEEED_WIO_TRACKER_L1", "Wio Tracker L1 hardware profile missing")
    require(hardware, "HardwareKind::BOARD_LILYGO_TBEAM", "T-Beam hardware profile missing")
    require(hardware, "HardwareKind::BOARD_LILYGO_TBEAM_SUPREME", "T-Beam Supreme hardware profile missing")

    # role_api=1 persistence is authoritative; proven legacy sources remain
    # only as a migration fallback for nodes not yet provisioned by the flasher.
    require(role_store, 'ROLE_PATH = "/prefs/jarnsen-role-v1"', "Unified persistent role record missing")
    require(role_store, "deviceRoleAllowedOnCurrentHardware(role)", "Role persistence is not board-gated")
    require(bridge, "if (readPersistedDeviceRole(role))", "Status bridge does not prefer the persistent role")
    require(bridge, "case meshtastic_Config_DeviceConfig_Role_TAK:", "Legacy TAK mapping missing")
    require(bridge, "case meshtastic_Config_DeviceConfig_Role_TAK_TRACKER:", "Legacy TAK_TRACKER mapping missing")
    require(bridge, "case meshtastic_Config_DeviceConfig_Role_REPEATER:",
            "Unified legacy REPEATER mapping missing")
    require(bridge, "role = DeviceRole::TAK_REPEATER;",
            "Legacy REPEATER no longer maps to the Unified TAK_REPEATER role")
    forbid(bridge, "#if defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V3)\n    case meshtastic_Config_DeviceConfig_Role_REPEATER:",
           "TAK_REPEATER legacy migration regressed to V3-only")
    require(bridge, "#if defined(JARNSEN_DRONE_REPEATER_BUILD)", "Drone-repeater build marker mapping missing")
    require(bridge, "role = DeviceRole::UNCONFIGURED;", "Unknown legacy roles no longer fail closed")
    require(serial, "JARNSEN_TOOL_ROLE_SET", "Unified persistent ROLE_SET command missing")
    require(serial, "JARNSEN_TOOL_ROLE_INFO", "Unified persistent ROLE_INFO command missing")
    require(serial, "role_api=1", "Unified role API capability is not advertised")
    require(drone_runtime, "DRONE_SMART_DISTANCE_M = 25U", "Drone Repeater runtime parity is missing")
    require(drone_runtime, "DRONE_LIGHT_SLEEP_CYCLE_SECS = 60U",
            "Drone Repeater ground light-sleep policy is missing")
    require(drone_runtime, "groundSleepEligible ? 0 : 1",
            "Drone Repeater can no longer stay awake while moving")

    require(power_fsm, "JARNSEN_POWERFSM_DISPLAY_WINDOW_V1", "Operator display timeout is not PowerFSM-owned")
    require(power_fsm, "JARNSEN_ROUTER_LIGHT_SLEEP_V2", "Repeater light-sleep transition is missing")
    require(tak_runtime, "JARNSEN_V3_WAKE_STABILITY_V2", "Bounded V3 wake stability guard is missing")
    require(tak_runtime, "JARNSEN_REPEATER_USB_AWAKE_V1", "Repeater can sleep while USB service is attached")
    require(common, "JARNSEN_TRACKER_SERVICE_TIMEBASE_V1", "Tracker service immediate-close guard is missing")
    require(common, "JARNSEN_TRACKER_BOOT_DISPLAY_WINDOW_V1", "Tracker boot page window is missing")
    require(common, "JARNSEN_TRACKER_SILENT_WAKE_DISPLAY_V1",
            "Tracker background wake display suppression is missing")
    require(common, "cause == ESP_SLEEP_WAKEUP_UNDEFINED || bootWasUserWake()",
            "Tracker display can no longer distinguish cold/button from motion/timer wake")
    require(common, "JARNSEN_FINAL_ACK_DEFERRED_PARK_V1", "FINAL_ACK deferred-park completion is missing")
    require(common, "JARNSEN_TAK_PARK_HEARTBEAT_SLEEP_V1", "TAK park-to-heartbeat light sleep is missing")
    require(power_fsm, "JARNSEN_TRACKER_DYNAMIC_LIGHT_SLEEP_V1", "Dynamic Tracker light-sleep deadline is missing")

    require(roles,
            "return {false, false, false, false, false, false, true, false, false, false, false};",
            "TAK role no longer requires light sleep")
    require(runtime_policy, "JARNSEN_TAK_ALWAYS_LISTEN_LIGHT_SLEEP_V1",
            "TAK always-listening LightSleep policy missing")
    require(runtime_policy, "meshtastic_Config_DeviceConfig_RebroadcastMode_ALL",
            "TAK role no longer guarantees normal mesh rebroadcast")
    require(power_fsm, "JARNSEN_TAK_LORA_WAKE_ROUTING_V1",
            "TAK LoRa wake routing state missing")

    # Tracker runtime must never run tracker GNSS/sleep policy for repeater roles.
    require(common,
            "return role == jarnsen::DeviceRole::TAK || role == jarnsen::DeviceRole::TAK_TRACKER;",
            "Tracker runtime role boundary changed")
    require(common, "role == jarnsen::DeviceRole::TAK_TRACKER", "TAK_TRACKER deep-sleep branch missing")
    require(common, "role == jarnsen::DeviceRole::TAK ? jarnsen::SleepMode::LIGHT_SLEEP",
            "TAK light-sleep branch missing")
    forbid(common, "DeviceRole::TAK_REPEATER ? jarnsen::SleepMode::DEEP_SLEEP",
           "Repeater role was accidentally routed into Tracker deep sleep")

    # ------------------------------------------------------------------
    # Position lifecycle: freshness -> final TX/fallback -> settle -> park.
    # ------------------------------------------------------------------
    require(settings, "uint8_t distanceIndex = 1;", "Smart-position default is no longer 75 m")
    require(settings, "uint8_t intervalIndex = 0;", "Smart-position minimum interval is no longer 30 s")
    require(settings, "uint8_t movingGnssIndex = 1;", "Moving GNSS default is no longer 10 s")
    require(settings, "uint8_t parkIndex = 2;", "Park heartbeat default is no longer 60 min")
    require(common, "#define TRACKER_COMMON_MOTION_QUIET_MS (120UL * 1000UL)", "Final-position quiet time changed")
    require(common, "#define TRACKER_COMMON_FINAL_GPS_WAIT_MS (30UL * 1000UL)", "Final GNSS wait changed")
    require(common, "#define TRACKER_COMMON_SLEEP_AFTER_POSITION_MS 8000UL", "Position settle time changed")
    require(common, "#define TRACKER_COMMON_FINAL_RECEIPT_WAIT_MS 4000UL",
            "FINAL_POS receipt wait changed")
    require(common, "#define TRACKER_COMMON_FINAL_RETRY_SETTLE_MS 3000UL",
            "FINAL_POS retry settle changed")
    require(settings, "uint32_t minSpanMs;", "Motion preset sustained-duration contract is missing")
    require(common, "spanMs >= trackerMotionConfirmMinSpanMs()",
            "Motion can again confirm from a short vibration burst")
    require(common, "nodeStateSyncPositionReceiptConfirmed(finalPositionPacketId)",
            "FINAL_POS no longer waits for JARNSEN cache receipt")
    require(common, "const uint32_t age = trackerLastFixAgeSecs();", "Fix freshness age guard missing")
    require(common, "gpsFixSince(finalPositionWaitStartedMs) && sendFreshPosition(false)",
            "Final-position fresh-fix path missing")
    require(common, "trackerDiagLog(\"FINAL_POS\", \"GNSS timeout; newest stored TX\")",
            "Final-position timeout/fallback diagnostic missing")
    require(common, "trackerDiagLog(\"TIMER_WAKE\", \"TAK_TRACKER fresh GNSS TX\")",
            "Deep-sleep heartbeat fresh TX missing")
    require(common, "trackerDiagLog(\"PARK_HEARTBEAT\", \"GNSS timeout; best stored TX\")",
            "Light-sleep heartbeat fallback missing")

    # ------------------------------------------------------------------
    # Power lifecycle: awake integration and sleep estimates must not mix.
    # ------------------------------------------------------------------
    require(power, "INA226_CONFIG_CONTINUOUS = 0x4127", "INA226 continuous mode changed")
    require(power, "INA226_CONFIG_POWER_DOWN = 0x4120", "INA226 power-down mode changed")
    require(power, "INA226_CONFIG_SLEEP_SINGLE = 0x41FB", "INA226 sleep one-shot conversion changed")
    require(power, "INA226_SLEEP_SHOT_MIN_US = 20000LL", "Sleep one-shot minimum capture window changed")
    require(power, "INA226_MAX_INTEGRATION_GAP_MS = 5000UL", "Awake INA integration gap guard changed")
    require(power, "if (sampleDeltaMs <= INA226_MAX_INTEGRATION_GAP_MS)", "Awake INA gap guard missing")
    require(power, "capacityWindowValid = false;", "Capacity learning is not invalidated after discontinuities")
    require(power, "powerStatus->getHasUSB() || powerStatus->getIsCharging()", "Battery learning no longer rejects external power")
    require(power, "inaCurrentUa < -INA226_DISCHARGE_DEADBAND_UA", "Capacity learning no longer rejects charge current")
    require(power, "void trackerPowerMonitorPrepareForLightSleep()", "Light-sleep power preparation missing")
    require(power, "void trackerPowerMonitorCompleteLightSleep()", "Light-sleep power completion missing")
    require(power, "void trackerPowerMonitorPrepareForDeepSleep(uint32_t plannedSleepSecs)", "Deep-sleep power preparation missing")
    require(power, "void recoverDeepSleepShot()", "Deep-sleep sample recovery missing")
    require(power, "estimate=sample_x_duration", "Sleep current is no longer explicitly labelled as an estimate")
    require(power_header, "sleepEstimatedMahX10", "Sleep energy is no longer separated from awake measured energy")
    require(power_header, "awakeMeasuredMahX10", "Awake INA energy is no longer separately exported")

    # Observer sequencing must bracket the real ESP light-sleep call.
    require_order(sleep, (
        "notifyLightSleep.notifyObservers(NULL)",
        "esp_light_sleep_start()",
        "notifyLightSleepEnd.notifyObservers(cause)",
    ), "ESP32 light-sleep observer lifecycle")
    require(common, "trackerPowerMonitorPrepareForLightSleep();", "Tracker INA light-sleep arm path missing")
    require(common, "trackerPowerMonitorCompleteLightSleep();", "Tracker INA light-sleep completion path missing")
    require_order(common, (
        "trackerPowerMonitorPrepareForDeepSleep(sleepMs / 1000UL);",
        "trackerRealDeepSleep(sleepMs, false, false);",
    ), "Tracker deep-sleep power handoff")
    require_order(sleep, (
        "waitEnterSleep(skipPreflight, true);",
        "notifyDeepSleep.notifyObservers(NULL);",
        "cpuDeepSleep(msecToWake);",
    ), "Deep-sleep shutdown lifecycle")

    # Important engineering boundary: static CI must not pretend it proves the
    # one-shot conversion actually landed inside the physical sleep plateau.
    require(beta_gate, "INA226 LightSleep entry-window", "Beta gate lacks INA226 LightSleep timing validation")
    require(beta_gate, "INA226 DeepSleep entry-window", "Beta gate lacks INA226 DeepSleep timing validation")
    require(beta_gate, "external current meter", "Beta gate lacks independent power-meter validation")
    require(unified_daily, "JARNSEN_LINKER_CACHE_RECOVERY_V1",
            "Unified build no longer self-recovers poisoned ESP-IDF linker caches")
    require(unified_daily, "is_stale_linker_cache_failure",
            "Unified build no longer detects stale memory.ld linker state")

    # ------------------------------------------------------------------
    # Service ownership: active transfers/OTA/USB must prevent unsafe sleep/close.
    # ------------------------------------------------------------------
    require(common, "const bool connectedQueue = queueHeld && nimbleBluetooth && nimbleBluetooth->isConnected();",
            "Connected BLE queue hard-cap protection missing")
    require(common, "!trackerDiagUsbExportPending() && !jarnsenServiceWebActive()",
            "USB/Web service no longer vetoes BLE service close")
    require(nimble, "setJarnsenBleQueueHold(true);", "BLE queue hold assertion missing")
    require(nimble, "setJarnsenBleQueueHold(false);", "BLE queue hold release missing")
    require(web, "if (!serviceActive || updateInProgress)", "Web OTA can now be stopped while an update is active")
    require(web, "JARNSEN_CAPTIVE_OPTION_114_V1",
            "Captive portal DHCP option 114 advertisement is missing")
    require(web, "JARNSEN_LOCAL_ONLY_AP_V2",
            "Local-only AP/mobile-data architecture is missing")
    require(web, "uint8_t routerOffer = 0U;",
            "ServiceWeb may not advertise the node as the phone default gateway")
    require(web, "postAuthDhcpSwitchRequestedMs",
            "Protected DHCP re-apply/retry state is missing")
    require(web, "JARNSEN_CAPTIVE_STABLE_AFTER_AUTH_V2",
            "Authenticated captive UI continuity contract is missing")
    require(web, "JARNSEN_EXPLICIT_CELLULAR_ROUTE_V1",
            "Explicit cellular Internet retry action is missing")
    require(web, 'id="cellularBtn"',
            "Cellular Internet retry control is missing")
    forbid(web, "esp_wifi_deauth_sta(0)",
           "Captive handoff may not forcibly disconnect the phone")
    require(web, "JARNSEN_CAPTIVE_PROBE_REDIRECT_V2",
            "Robust captive probe redirect is missing")
    require(web, "captiveHostIsLocal",
            "Foreign captive hosts are no longer canonicalized to the node IP")
    require(web, "JARNSEN_CAPTIVE_AUTO_OPEN_V1",
            "Automatic captive portal routing is missing")
    require(web, "JARNSEN_BROWSER_LOCAL_GPS_V1",
            "Browser-only phone GPS contract is missing")
    require(web, "JARNSEN_SERVICE_HTTPS_V1",
            "Provisioned JARNSEN HTTPS service is missing")
    require(web, 'HTTPSServer(serviceHttpsCert, 443, 1)',
            "JARNSEN HTTPS service is not bound to port 443")
    require(web, "/jarnsen-root-ca.cer",
            "Direct JARNSEN Root-CA certificate endpoint is missing")
    require(web, "application/x-x509-ca-cert",
            "Direct JARNSEN Root-CA certificate MIME type is missing")
    require(web, "location.replace('https://192.168.4.1/')",
            "Trusted Root-CA no longer causes automatic HTTPS handoff")
    require(web, "window.isSecureContext",
            "Phone GPS is not gated to HTTPS/secure contexts")
    require(web, "navigator.geolocation.watchPosition",
            "Secure browser phone GPS tracking is missing")
    forbid(web, 'strncmp(path, "/phone-position?", 16) == 0',
           "Browser phone position is being uploaded to the node")
    forbid(web, "JarnsenTrackSource::PHONE",
           "Browser phone position leaked into node track storage")
    require(web, "nodeSelfPos",
            "Connected node and phone EIGEN position are no longer separated")
    require(web, "ctx.moveTo(0,-36)",
            "Own-position map arrow is too small/regressed")
    require(web, "defined(TBEAM_V10)",
            "Classic T-Beam is excluded from ServiceWeb")
    require(web, "defined(LILYGO_TBEAM_S3_CORE)",
            "T-Beam Supreme is excluded from ServiceWeb")
    require(web_header, "defined(TBEAM_V10)",
            "Classic T-Beam is excluded from ServiceWeb header")
    require(web_header, "defined(LILYGO_TBEAM_S3_CORE)",
            "T-Beam Supreme is excluded from ServiceWeb header")
    require(web, "Update.begin(contentLength, U_FLASH)", "Web OTA no longer targets firmware update partition")
    require(serial, "s_jarnsenServiceTakeover = true;", "JARNSEN USB service cannot take ownership after protobuf")
    require(serial, "usingProtobufs = false;", "USB service takeover no longer releases protobuf mode")
    require(diag, "===JARNSEN_DIAG_LOG_BEGIN===", "Diagnostic BEGIN marker missing")
    require(diag, "===JARNSEN_DIAG_LOG_END===", "Diagnostic END marker missing")

    print("JARNSEN final parity/lifecycle audit: PASS")
    print("- role intent is separated from board/peripheral capabilities")
    print("- Tracker runtime is bounded to TAK/TAK_TRACKER, not repeater roles")
    print("- GNSS freshness/final/heartbeat ordering remains explicit")
    print("- awake INA integration and sleep estimates remain separated")
    print("- service/OTA/USB ownership guards remain intact")
    print("- physical sleep-current timing is intentionally deferred to the beta hardware gate")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditFailure as exc:
        print(f"JARNSEN final parity/lifecycle audit: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
