#!/usr/bin/env python3
"""Tracker runtime reliability contracts for the Unified Core gate."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


class ContractFailure(RuntimeError):
    pass


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise ContractFailure(f"required file missing: {rel}")
    return path.read_text(encoding="utf-8")


def require(text: str, needle: str, message: str) -> None:
    if needle not in text:
        raise ContractFailure(message)


def main() -> int:
    common = read("src/vehicle/TrackerCommonPolicy.cpp")
    settings = read("src/vehicle/TrackerServiceSettings.cpp")
    upgrade = read("src/vehicle/TrackerServiceUpgrade.cpp")
    web = read("src/mesh/http/JarnsenServiceWeb.cpp")
    nimble = read("src/nimble/NimbleBluetooth.cpp")

    # GNSS / position policy defaults and final-position timing.
    require(settings, 'constexpr uint16_t DISTANCE_PRESETS[] = {50, 75, 100, 150};',
            "Tracker smart-position distance presets changed")
    require(settings, 'uint8_t distanceIndex = 1;', "Tracker smart-position default is no longer 75 m")
    require(settings, 'constexpr uint16_t INTERVAL_PRESETS[] = {30, 45, 60, 90};',
            "Tracker smart-position interval presets changed")
    require(settings, 'uint8_t intervalIndex = 0;', "Tracker smart-position minimum interval is no longer 30 s")
    require(settings, 'constexpr uint16_t MOVING_GNSS_PRESETS[] = {5, 10, 15, 30};',
            "Tracker moving-GNSS presets changed")
    require(settings, 'uint8_t movingGnssIndex = 1;', "Tracker moving-GNSS default is no longer 10 s")
    require(settings, 'uint8_t parkIndex = 2;', "Tracker parked heartbeat default is no longer 60 min")
    require(settings, 'uint8_t parkGpsSearchIndex = 1;', "Tracker parked GNSS search default is no longer 30 s")
    require(settings, 'config.position.position_broadcast_smart_enabled = true;', "Smart position is not enabled")
    require(settings, 'config.position.broadcast_smart_minimum_distance = trackerSmartDistanceM();',
            "Smart distance is not applied through Tracker settings")
    require(settings, 'config.position.broadcast_smart_minimum_interval_secs = trackerSmartIntervalSecs();',
            "Smart minimum interval is not applied through Tracker settings")

    require(common, '#define TRACKER_COMMON_MOTION_QUIET_MS (120UL * 1000UL)',
            "Final-position quiet period is no longer 120 s")
    require(common, '#define TRACKER_COMMON_FINAL_GPS_WAIT_MS (30UL * 1000UL)',
            "Final-position GNSS wait is no longer 30 s")
    require(common, '#define TRACKER_COMMON_SLEEP_AFTER_POSITION_MS 8000UL',
            "Post-position sleep settle is no longer 8 s")
    require(common, 'if (gpsFixSince(lastMotionMs) && sendFreshPosition(false))',
            "Final position no longer prefers a fresh post-motion fix")
    require(common, 'trackerDiagLog("FINAL_POS", "GNSS timeout; newest stored TX")',
            "Final-position fallback diagnostic is missing")
    require(common, 'sendBestPosition(false);', "Final-position stored-position fallback is missing")
    require(common, 'trackerDiagLog("TIMER_WAKE", "TAK_TRACKER fresh GNSS TX")',
            "Deep-sleep timer heartbeat fresh-fix path is missing")
    require(common, 'trackerDiagLog("TIMER_WAKE", "TAK_TRACKER GNSS timeout after %us; newest stored TX"',
            "Deep-sleep timer heartbeat fallback is missing")
    require(common, 'trackerDiagLog("PARK_HEARTBEAT", "due; GNSS wake requested")',
            "Light-sleep parked heartbeat GNSS wake is missing")
    require(common, 'trackerDiagLog("PARK_HEARTBEAT", "fresh fix TX after %us"',
            "Light-sleep parked heartbeat fresh TX diagnostic is missing")
    require(common, 'trackerDiagLog("PARK_HEARTBEAT", "GNSS timeout; best stored TX")',
            "Light-sleep parked heartbeat fallback diagnostic is missing")
    require(common, 'const uint32_t age = trackerLastFixAgeSecs();', "Position freshness no longer tracks fix age")

    # BLE service reliability: activity, queue hold and timeout protections.
    require(common, 'trackerDiagLog("BT_SERVICE", "opened/resumed")', "BLE service-open diagnostic is missing")
    require(common, 'trackerDiagLog("BT_SERVICE", "closed/suspended")', "BLE service-close diagnostic is missing")
    require(common, 'trackerDiagLog("BT_ACTIVITY", "meaningful burst; idle timer reset")',
            "Meaningful BLE traffic no longer resets/logs the idle timer")
    require(common, 'const bool queueHeld = bleQueueHold.load();', "BLE queue-hold state is not considered by timeout logic")
    require(common, 'const bool connectedQueue = queueHeld && nimbleBluetooth && nimbleBluetooth->isConnected();',
            "Connected BLE queue is not protected from the hard cap")
    require(common, '!trackerDiagUsbExportPending() && !jarnsenServiceWebActive()',
            "USB export / service web no longer block BLE timeout closure")
    require(common, '((hardCap && !connectedQueue) || (!queueHeld && idle))',
            "BLE idle/hard-cap decision no longer preserves an active connected queue")
    require(nimble, 'setJarnsenBleQueueHold(true);', "BLE queue hold can no longer be asserted")
    require(nimble, 'setJarnsenBleQueueHold(false);', "BLE queue hold can no longer be released")
    require(nimble, 'jarnsenOtaQueueHold = true;', "BLE OTA no longer records queue hold")
    require(nimble, 'if (!jarnsenOtaRebootPending.load() && jarnsenOtaQueueHold.exchange(false))',
            "Disconnect cleanup no longer releases stale OTA queue hold")

    # Runtime diagnostics added by this reliability block.
    require(upgrade, 'trackerDiagLog("BLE_DISCONNECT"', "BLE disconnect diagnostic is missing")
    require(upgrade, 'trackerDiagLog("BLE_RECONNECT"', "BLE reconnect diagnostic is missing")
    require(upgrade, 'trackerDiagLog("WEB_SERVICE"', "Web-service hold/release diagnostic is missing")
    require(upgrade, 'trackerDiagLog("BLE_TRANSFER"', "BLE transfer hold/release diagnostic is missing")

    # WLAN OTA remains the existing inactive-partition Update path; do not replace it.
    require(web, 'Update.begin(contentLength, U_FLASH)', "Service Web OTA no longer targets the firmware update partition")
    require(web, 'if (!Update.end(false))', "Service Web OTA validation/activation is missing")
    require(web, 'logEvent("WLAN_OTA_OK", hashText);', "Service Web OTA success diagnostic is missing")
    require(web, 'logEvent("WLAN_OTA_FAIL", message);', "Service Web OTA failure diagnostic is missing")
    require(web, 'if (!serviceActive || updateInProgress)', "Service Web can now stop while OTA is active")

    print("JARNSEN tracker runtime reliability contracts: PASS")
    print("- GNSS defaults, 120s final-position flow, 30s fallback and 8s settle")
    print("- deep-sleep timer and light-sleep parked heartbeat paths")
    print("- BLE activity, queue hold, export/web guards and connected hard-cap protection")
    print("- BLE disconnect/reconnect, transfer and service-web transition diagnostics")
    print("- existing WLAN OTA inactive-partition safety path retained")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractFailure as exc:
        print(f"JARNSEN tracker runtime reliability contracts: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
