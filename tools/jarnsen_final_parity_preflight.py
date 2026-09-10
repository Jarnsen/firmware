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
    common = read("src/vehicle/TrackerCommonPolicy.cpp")
    power = read("src/vehicle/TrackerPowerMonitor.cpp")
    power_header = read("src/vehicle/TrackerPowerMonitor.h")
    settings = read("src/vehicle/TrackerServiceSettings.cpp")
    sleep = read("src/sleep.cpp")
    serial = read("src/SerialConsole.cpp")
    diag = read("src/jarnsen/core/service/JarnsenDiagnosticLog.cpp")
    web = read("src/mesh/http/JarnsenServiceWeb.cpp")
    nimble = read("src/nimble/NimbleBluetooth.cpp")
    beta_gate = read("docs/JARNSEN_BETA_HARDWARE_GATE.md")

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
    require(bridge, "#if defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V3)", "V3-only repeater mapping guard missing")
    require(bridge, "case meshtastic_Config_DeviceConfig_Role_REPEATER:", "Proven V3 repeater mapping missing")
    require(bridge, "#if defined(JARNSEN_DRONE_REPEATER_BUILD)", "Drone-repeater build marker mapping missing")
    require(bridge, "role = DeviceRole::UNCONFIGURED;", "Unknown legacy roles no longer fail closed")
    require(serial, "JARNSEN_TOOL_ROLE_SET", "Unified persistent ROLE_SET command missing")
    require(serial, "JARNSEN_TOOL_ROLE_INFO", "Unified persistent ROLE_INFO command missing")
    require(serial, "role_api=1", "Unified role API capability is not advertised")
    require(drone_runtime, "DRONE_SMART_DISTANCE_M = 25U", "Drone Repeater runtime parity is missing")

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
