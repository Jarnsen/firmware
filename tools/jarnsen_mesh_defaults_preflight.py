#!/usr/bin/env python3
"""Approved TAK Netz 26 target contract; deliberately not a firmware-pass assertion.

The approved primary channel, MEDIUM_SLOW and 7-hop defaults are now
implemented in the firmware's fresh-config path. The shared AES-256 PSK is
never compiled into firmware; operational readiness still requires private
master QR provisioning and hardware read-back on each supported board.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "config" / "jarnsen-mesh-network-target.json"

EXPECTED = {
    "contract_version": 1,
    "rollout_state": "implemented_pending_key_provisioning_and_hardware_verification",
    "scope": {
        "primary_channel_applies_to": [
            "TAK",
            "TAK_TRACKER",
            "TAK_REPEATER",
            "DRONE_REPEATER"
        ],
        "supported_hardware": [
            "Heltec Tracker V1.1",
            "Heltec V3",
            "Heltec V4",
            "Seeed Wio Tracker L1",
            "LILYGO T-Beam",
            "LILYGO T-Beam Supreme"
        ]
    },
    "primary_channel": {
        "index": 0,
        "name": "TAK Netz 26",
        "encryption": "AES-256",
        "key_bits": 256,
        "key_material": "secure_per_network_provisioning_not_in_repository",
        "position_precision_bits": 32,
        "uplink_enabled": False,
        "downlink_enabled": False
    },
    "radio": {
        "region": "EU_868",
        "modem_preset": "MEDIUM_SLOW",
        "hop_limit": 7,
        "tx_enabled": True,
        "tx_power_dbm": 0,
        "frequency_override_mhz": 0,
        "override_duty_cycle": False,
        "ignore_mqtt": True,
        "rx_boosted_gain": "if_supported"
    },
    "excluded_from_shared_contract": [
        "node_name",
        "node_id",
        "gps_policy",
        "sleep_policy",
        "position_reporting_policy",
        "rebroadcast_mode",
        "device_https_certificate"
    ]
}

def main() -> int:
    data = json.loads(SPEC.read_text(encoding="utf-8"))
    if data != EXPECTED:
        raise SystemExit(
            "TAK Netz 26 target contract: FAIL (approved channel/LoRa/default "
            "parameters changed or undocumented fields added)"
        )
    if data["rollout_state"] != "implemented_pending_key_provisioning_and_hardware_verification":
        raise SystemExit("TAK Netz 26 rollout state drifted from implemented, pending hardware verification")
    header = (ROOT / "src/jarnsen/core/mesh/JarnsenNetworkDefaults.h").read_text(encoding="utf-8")
    nodedb = (ROOT / "src/mesh/NodeDB.cpp").read_text(encoding="utf-8")
    channels = (ROOT / "src/mesh/Channels.cpp").read_text(encoding="utf-8")
    runtime = (ROOT / "src/jarnsen/core/runtime/JarnsenRuntimePolicy.cpp").read_text(encoding="utf-8")
    expected_code = {
        "primary name": (header, 'TAK_NETWORK_PRIMARY_NAME[] = "TAK Netz 26"'),
        "EU region": (header, "meshtastic_Config_LoRaConfig_RegionCode_EU_868"),
        "MEDIUM_SLOW": (header, "meshtastic_Config_LoRaConfig_ModemPreset_MEDIUM_SLOW"),
        "seven hops": (header, "TAK_NETWORK_HOPS = 7U"),
        "TX AUTO": (header, "TAK_NETWORK_TX_AUTO = 0"),
        "position precision": (header, "TAK_NETWORK_POSITION_PRECISION_BITS = 32U"),
        "all-board gate": (header, "JARNSEN_NETWORK_TARGET_BOARD 1"),
        "NodeDB guarded initial defaults": (nodedb, "#if JARNSEN_NETWORK_TARGET_BOARD"),
        "NodeDB initial region": (nodedb, "config.lora.region = jarnsen::TAK_NETWORK_REGION;"),
        "NodeDB initial medium slow": (nodedb, "config.lora.modem_preset = jarnsen::TAK_NETWORK_MODEM;"),
        "NodeDB initial hop count": (nodedb, "config.lora.hop_limit = jarnsen::TAK_NETWORK_HOPS;"),
        "NodeDB disable MQTT": (nodedb, "moduleConfig.mqtt.enabled = false;"),
        "default channel name": (channels, "jarnsen::TAK_NETWORK_PRIMARY_NAME"),
        "default channel position": (channels, "jarnsen::TAK_NETWORK_POSITION_PRECISION_BITS"),
        "pending key no public fallback": (channels, "channelSettings.psk.size = 0U;"),
        "safe TX gate": (channels, "config.lora.tx_enabled = false;"),
        "fresh radio profile": (channels, "loraConfig.modem_preset = jarnsen::TAK_NETWORK_MODEM;"),
        "configured EU repair": (runtime, "config.lora.region = meshtastic_Config_LoRaConfig_RegionCode_EU_868;"),
        "configured MEDIUM_SLOW repair": (runtime, "config.lora.modem_preset = meshtastic_Config_LoRaConfig_ModemPreset_MEDIUM_SLOW;"),
        "runtime TX AUTO": (runtime, "config.lora.tx_power = 0;"),
    }
    for label, (source, anchor) in expected_code.items():
        if anchor not in source:
            raise SystemExit(f"TAK Netz 26 firmware integration: FAIL ({label})")
    for board in ("HELTEC_TRACKER_V1_1", "HELTEC_V3", "HELTEC_V4",
                  "SEEED_WIO_TRACKER_L1", "TBEAM_V10", "LILYGO_TBEAM_S3_CORE"):
        if board not in header:
            raise SystemExit(f"TAK Netz 26 board not covered: {board}")
    if '"TAK Netz 26"' in nodedb or "TAK Netz 26" in channels and "pending AES-256" not in channels:
        raise SystemExit("TAK Netz 26 should use the shared defaults header, not duplicated board-specific constants")
    if "JARNSEN_NETWORK_TARGET_BOARD" not in nodedb or "JARNSEN_NETWORK_TARGET_BOARD" not in channels:
        raise SystemExit("TAK Netz 26 defaults are not scoped to JARNSEN boards")

    text = SPEC.read_text(encoding="utf-8")
    if "-----BEGIN" in text or "AQ==" in text or '"psk"' in text:
        raise SystemExit("TAK Netz 26 contract: key material must not be committed")
    print(
        "TAK Netz 26 target contract: PASS "
        "(PRIMARY index=0, MEDIUM_SLOW, EU_868, 7 hops, AES-256, TX AUTO)"
    )
    print("::notice::TAK Netz 26 firmware defaults: IMPLEMENTED; shared AES-256 key provisioning and device verification: PENDING")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
