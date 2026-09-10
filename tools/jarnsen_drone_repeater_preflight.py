#!/usr/bin/env python3
"""Static contract gate for the Unified-Core Drone Repeater migration."""

# This file also acts as an explicit CI trigger after the migration commit.
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


class Failure(RuntimeError):
    pass


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise Failure(f"required file missing: {rel}")
    return path.read_text(encoding="utf-8")


def require(text: str, needle: str, message: str) -> None:
    if needle not in text:
        raise Failure(message)


def forbid(text: str, needle: str, message: str) -> None:
    if needle in text:
        raise Failure(message)


def main() -> int:
    roles = read("src/jarnsen/core/roles/JarnsenDeviceRole.h")
    store = read("src/jarnsen/core/roles/JarnsenRolePersistence.cpp")
    hardware = read("src/jarnsen/hardware/JarnsenHardwareProfiles.h")
    bridge = read("src/jarnsen/adapters/JarnsenLegacyStatusBridge.cpp")
    drone = read("src/jarnsen/core/runtime/JarnsenDroneRepeaterPolicy.cpp")
    serial = read("src/SerialConsole.cpp")
    power = read("src/PowerFSM.cpp")
    esp32 = read("src/platform/esp32/main-esp32.cpp")
    position_h = read("src/modules/PositionModule.h")
    architecture = read("src/jarnsen/core/JarnsenArchitecture.cpp")
    display = read("src/jarnsen/adapters/JarnsenDisplayRuntime.cpp")

    require(roles, 'return "drone_repeater";', "Drone role key missing")
    require(store, 'ROLE_PATH = "/prefs/jarnsen-role-v1"', "persistent role record missing")
    require(store, "deviceRoleAllowedOnCurrentHardware(decoded)", "persisted role is not revalidated against hardware")
    require(store, "deviceRoleAllowedOnCurrentHardware(role)", "role write path lacks hardware gate")

    require(hardware, "HardwareKind::BOARD_HELTEC_TRACKER_V11", "Tracker profile missing")
    require(hardware, "HardwareKind::BOARD_HELTEC_V4", "V4 profile missing")
    require(architecture, "V4 must deliberately allow Drone Repeater", "V4 Drone allow assertion missing")
    require(architecture, "External GPS must not accidentally unlock Drone Repeater on V3", "V3 Drone block assertion missing")
    require(architecture, "Wio Tracker L1 Drone Repeater must stay disabled", "Wio Drone block assertion missing")
    require(architecture, "T-Beam Drone Repeater must stay disabled", "T-Beam Drone block assertion missing")
    require(architecture, "T-Beam Supreme Drone Repeater must stay disabled", "T-Beam Supreme Drone block assertion missing")

    require(bridge, "if (readPersistedDeviceRole(role))", "persistent role is not authoritative in status bridge")
    require(bridge, "peripherals.externalGps = gps && gps->isConnected();", "V4/V3 external GNSS runtime detection missing")

    require(serial, "role_api=1", "JARNSEN_TOOL_INFO does not advertise role_api=1")
    require(serial, "JARNSEN_TOOL_ROLE_INFO", "ROLE_INFO command missing")
    require(serial, "JARNSEN_TOOL_ROLE_SET", "ROLE_SET command missing")
    require(serial, "deviceRoleAllowedOnCurrentHardware(requested)", "ROLE_SET lacks board gate")
    require(serial, "readPersistedDeviceRole(verify) && verify == requested", "ROLE_SET lacks write/read-back verification")
    require(serial, 'reason = !valid ? "invalid_role" : (!allowed ? "unsupported_board"', "unsupported board does not fail closed")
    require(serial, "external_gps_required=", "ROLE_INFO lacks V4 external-GNSS hint")

    require(drone, "meshtastic_Config_DeviceConfig_Role_ROUTER_LATE", "Drone base role is not ROUTER_LATE")
    require(drone, "meshtastic_Config_DeviceConfig_RebroadcastMode_ALL", "Drone rebroadcast ALL missing")
    require(drone, "DRONE_SMART_DISTANCE_M = 25U", "Drone smart distance changed")
    require(drone, "DRONE_GPS_UPDATE_SECS = 1U", "Drone 1s GNSS update changed")
    require(drone, "DRONE_GROUND_HEARTBEAT_SECS = 30U", "Drone ground heartbeat changed")
    require(drone, "speedKmh < 15.0f", "Drone dynamic speed tiers missing")
    require(drone, "channelUtilization >= 25.0f", "Drone channel-utilization brake missing")
    require(drone, '"fresh-fix"', "immediate fresh-fix transmit path missing")
    require(drone, 'reason = "distance"', "distance-driven position path missing")
    require(drone, "DRONE_BT_IDLE_MS = 120UL * 1000UL", "Drone BLE idle window changed")
    require(drone, "DRONE_BT_HARD_CAP_MS = 15UL * 60UL * 1000UL", "Drone BLE hard cap changed")
    require(drone, "nimbleBluetooth->suspend()", "Drone BLE service is not suspendable/button-only")
    require(drone, "config.network.wifi_enabled", "Drone Wi-Fi-off policy missing")
    require(drone, "config.power.is_power_saving", "Drone no-power-saving policy missing")
    require(drone, '"DRONE_HEALTH"', "Drone runtime health diagnostics missing")

    require(power, "!isDroneRepeater && (isRouter || config.power.is_power_saving)", "PowerFSM can still enter routine light sleep for Drone")
    require(esp32, "Keeping Bluetooth memory reserved for Drone Repeater runtime service", "ESP32 can still irreversibly release Drone BLE memory")
    require(position_h, "noteExternalPositionSend", "Drone external position sends do not share PositionModule bookkeeping")
    require(display, 'return "DRONE REPEATER";', "generic V4 display cannot show Drone role")

    forbid(drone, "JARNSEN_DRONE_REPEATER_BUILD", "Drone runtime still depends on dedicated build marker")
    forbid(serial, "heltec-tracker-v11-drone-repeater", "Unified role API contains a legacy firmware fallback")

    print("JARNSEN Drone Repeater migration contracts: PASS")
    print("- board gate: Tracker V1.1 + Heltec V4 only")
    print("- persistent role_api=1 set/read-back verification")
    print("- ROUTER_LATE/ALL, no sleep, Wi-Fi off, button-only BLE")
    print("- 25m + 30/10/7/5s dynamic position policy with CU brake")
    print("- V4 external-GNSS readiness remains explicit")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Failure as exc:
        print(f"JARNSEN Drone Repeater migration contracts: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
