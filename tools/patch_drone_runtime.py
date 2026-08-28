#!/usr/bin/env python3
"""Build-time integration hooks for the dedicated Tracker V1.1 drone profile.

The drone code stays isolated under src/drone. This patch only touches upstream
hotspots where a compile-time hook is required: PowerFSM and RadioLibInterface.
Every replacement is exact and fails the build if upstream changes invalidate an
anchor, so the branch cannot silently lose the no-sleep or observability policy.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, got {count}")
    return text.replace(old, new, 1)


power_path = ROOT / "src/PowerFSM.cpp"
power = power_path.read_text(encoding="utf-8")
power = replace_once(
    power,
    "static bool isPowered()\n{\n",
    "static bool isPowered()\n{\n"
    "#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)\n"
    "    // Dedicated airborne profile: LoRa RX and GNSS must never enter a\n"
    "    // sleep state just because VBUS disappears. Real USB/battery source\n"
    "    // changes are monitored separately by DronePowerMonitor.\n"
    "    return true;\n"
    "#endif\n",
    "PowerFSM drone always-awake hook",
)
power = replace_once(
    power,
    "#if defined(HELTEC_TRACKER_V1_1)\n"
    "    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||\n"
    "           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;\n",
    "#if defined(HELTEC_TRACKER_V1_1)\n"
    "#if defined(JARNSEN_DRONE_REPEATER_BUILD)\n"
    "    // Drone policy owns BLE and display even though its role is ROUTER_LATE.\n"
    "    return true;\n"
    "#else\n"
    "    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||\n"
    "           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;\n"
    "#endif\n",
    "PowerFSM drone interactive ownership",
)
power_path.write_text(power, encoding="utf-8")

radio_path = ROOT / "src/mesh/RadioLibInterface.cpp"
radio = radio_path.read_text(encoding="utf-8")
radio = replace_once(
    radio,
    "#endif\n#include <pb_decode.h>\n",
    "#endif\n"
    "#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)\n"
    "#include \"drone/DroneMeshHealth.h\"\n"
    "#include \"drone/DronePowerMonitor.h\"\n"
    "#endif\n"
    "#include <pb_decode.h>\n",
    "RadioLib drone includes",
)
radio = replace_once(
    radio,
    "        txGood++;\n"
    "        if (!isFromUs(p))\n"
    "            txRelay++;\n"
    "        printPacket(\"Completed sending\", p);\n",
    "        txGood++;\n"
    "        const bool relayPacket = !isFromUs(p);\n"
    "        if (relayPacket)\n"
    "            txRelay++;\n"
    "#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)\n"
    "        dronePowerMonitorNoteRadioTx(relayPacket);\n"
    "#endif\n"
    "        printPacket(\"Completed sending\", p);\n",
    "RadioLib drone TX counter",
)
radio = replace_once(
    radio,
    "            addReceiveMetadata(mp);\n\n"
    "            mp->which_payload_variant =\n",
    "            addReceiveMetadata(mp);\n"
    "#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)\n"
    "            droneMeshHealthOnRadioPacket(*mp);\n"
    "#endif\n\n"
    "            mp->which_payload_variant =\n",
    "RadioLib drone RX observer",
)
radio_path.write_text(radio, encoding="utf-8")

print("Drone runtime hooks applied: always-awake + radio observability")
