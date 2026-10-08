#!/usr/bin/env python3
"""Approved TAK Netz 26 target contract; deliberately not a firmware-pass assertion.

The user approved the primary channel and MEDIUM_SLOW/7-hop target, but has
not approved writing these settings to firmware yet. Until implementation,
this preflight protects the agreed values from drift and reports PENDING.
Hardware/flash read-back belongs in the beta hardware gate.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "config" / "jarnsen-mesh-network-target.json"

EXPECTED = {
    "contract_version": 1,
    "rollout_state": "pending_implementation",
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
    if data["rollout_state"] != "pending_implementation":
        raise SystemExit(
            "TAK Netz 26 implementation cannot be declared complete by "
            "changing the JSON state alone. Add source and live-device checks first."
        )
    text = SPEC.read_text(encoding="utf-8")
    if "-----BEGIN" in text or "AQ==" in text or '"psk"' in text:
        raise SystemExit("TAK Netz 26 contract: key material must not be committed")
    print(
        "TAK Netz 26 target contract: PASS "
        "(PRIMARY index=0, MEDIUM_SLOW, EU_868, 7 hops, AES-256, TX AUTO)"
    )
    print("::notice::TAK Netz 26 firmware implementation: PENDING, hardware verification: PENDING")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
