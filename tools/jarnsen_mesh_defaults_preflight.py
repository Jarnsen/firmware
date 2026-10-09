#!/usr/bin/env python3
"""Approved TAK Netz 26 target contract; deliberately not a firmware-pass assertion.

The approved primary channel, MEDIUM_SLOW and 7-hop defaults are now
implemented in the firmware's fresh-config path. The 32-byte master PSK
is compiled from an encrypted build secret, NOT from a manually scanned QR.
Firmware binaries include the extractable key; protect distribution.
Physical hardware read-back is still required on every supported board.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "config" / "jarnsen-mesh-network-target.json"

EXPECTED = {
    "contract_version": 1,
    "rollout_state": "implemented_pending_secret_and_hardware_verification",
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
        "key_material": "embedded_at_build_from_encrypted_secret",
        "key_sha256": "03d48375a4553f77f274941033d745211abd7e88cfe3f03141a20747906eb6dc",
        "channel_id": 4026805322,
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

def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def main() -> int:
    data = json.loads(SPEC.read_text(encoding="utf-8"))
    if data != EXPECTED:
        raise SystemExit(
            "TAK Netz 26 target contract: FAIL (approved channel/LoRa/default "
            "parameters changed or undocumented fields added)"
        )
    if data["rollout_state"] != "implemented_pending_secret_and_hardware_verification":
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
        "protected-build-key injection": (header, '#include "JarnsenNetworkKey.generated.h"'),
        "embedded AES-256 copy": (channels, "jarnsen::TAK_NETWORK_PRIMARY_PSK"),
        "AES-256 key length": (channels, "channelSettings.psk.size = sizeof(jarnsen::TAK_NETWORK_PRIMARY_PSK);"),
        "same master channel ID": (channels, "channelSettings.id = jarnsen::TAK_NETWORK_PRIMARY_ID;"),
        "staged Build 410 migration": (nodedb, "Build 410 staged primary automatically activated"),
        "staged TX enable": (nodedb, "config.lora.tx_enabled = true;"),
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
    if '"TAK Netz 26"' in nodedb or "TAK Netz 26" in channels and "embedded AES-256 primary" not in channels:
        raise SystemExit("TAK Netz 26 should use the shared defaults header, not duplicated board-specific constants")
    if "JARNSEN_NETWORK_TARGET_BOARD" not in nodedb or "JARNSEN_NETWORK_TARGET_BOARD" not in channels:
        raise SystemExit("TAK Netz 26 defaults are not scoped to JARNSEN boards")

    generator = read("tools/jarnsen_prepare_network_key.py")
    runner = read(".buildkite/run-unified-build.sh")
    workflow = read(".github/workflows/build-jarn-mesh-unified-core.yml")
    gitignore = read(".gitignore")
    if (
        "JARNSEN_TAK_NET_26_PSK_HEX" not in generator
        or data["primary_channel"]["key_sha256"] not in generator
        or "OUTPUT.unlink(missing_ok=True)" not in generator
        or "raise SystemExit" not in generator
    ):
        raise SystemExit("TAK Netz 26 protected key validation missing or not fail-closed")
    if "python3 tools/jarnsen_prepare_network_key.py" not in runner:
        raise SystemExit("TAK Netz 26 protected key generator is not in firmware compile path")
    supreme_workflow = read(".github/workflows/test-jarnsen-tbeam-supreme.yml")
    if 'rm -f "$ROOT/src/jarnsen/core/mesh/JarnsenNetworkKey.generated.h"' not in workflow:
        raise SystemExit("TAK Netz 26 generated key might leak into source archive")
    if "Secret-bearing generated header detected in source bundle" not in workflow:
        raise SystemExit("TAK Netz 26 source artifact does not fail-closed on key-file leakage")
    if workflow.count("secrets.JARNSEN_TAK_NET_26_PSK_HEX") != 3:
        raise SystemExit("TAK Netz 26 protected key missing for one or more Unified Core build jobs")
    if supreme_workflow.count("secrets.JARNSEN_TAK_NET_26_PSK_HEX") != 1:
        raise SystemExit("TAK Netz 26 protected key missing from T-Beam Supreme smoke build")
    # Keep the Supreme out of routine push builds to save runner time.
    # A complete release is still blocked unless the Supreme matrix job
    # passes; the separate smoke remains available by manual dispatch.
    supreme_smoke = read(".github/workflows/test-jarnsen-tbeam-supreme.yml")
    unified_release = workflow
    smoke_triggers = supreme_smoke.split("on:", 1)[1].split("concurrency:", 1)[0]
    if "push:" in smoke_triggers or "workflow_dispatch:" not in smoke_triggers:
        raise SystemExit("T-Beam Supreme smoke must be manual only")
    if (
        "- name: LILYGO T-Beam Supreme" not in unified_release
        or "environment: tbeam-s3-core" not in unified_release
        or "if: github.event_name == 'workflow_dispatch' && inputs.build_scope == 'full'" not in unified_release
        or "needs: [tracker, v3, compile_full, uploads]" not in unified_release
    ):
        raise SystemExit("T-Beam Supreme must remain a release-blocking full-build matrix target")

    if "JarnsenNetworkKey.generated.h" not in gitignore:
        raise SystemExit("TAK Netz 26 protected generated file not in gitignore")
    if "channelSettings.psk.size = 0U;" in channels or "pending AES-256 master QR" in channels:
        raise SystemExit("TAK Netz 26 QR-required channel must no longer be active")
    if f'TAK_NETWORK_PRIMARY_ID = {data["primary_channel"]["channel_id"]}U' not in header:
        raise SystemExit("TAK Netz 26 master channel ID mismatched")
    text = SPEC.read_text(encoding="utf-8")
    if "-----BEGIN" in text or '"psk"' in text:
        raise SystemExit("TAK Netz 26 contract must not include literal secrets")
    print(
        "TAK Netz 26 target contract: PASS "
        "(PRIMARY index=0, MEDIUM_SLOW, EU_868, 7 hops, AES-256, TX AUTO)"
    )
    print("::notice::TAK Netz 26 master-key build pipeline IMPLEMENTED; encrypted secret configuration / on-device verification: PENDING")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
