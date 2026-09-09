"""Regression contracts for Framework7 destructive-action hardening.

Runs without attached hardware. It proves the built source rejects unsafe image
names/contracts and that all three hardening layers are actually wired into both
Framework7 start paths before the Windows package is produced.
"""
from __future__ import annotations

import pathlib
import sys
import traceback

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import JARNSEN_FRAMEWORK7_SERIES as series  # noqa: E402
import JARNSEN_FRAMEWORK7_SERIES_HARDENING as hard  # noqa: E402


def expect_error(callback, marker: str) -> None:
    try:
        callback()
    except RuntimeError as exc:
        if marker.lower() not in str(exc).lower():
            raise AssertionError(f"expected error containing {marker!r}, got {exc!r}") from exc
    else:
        raise AssertionError(f"expected RuntimeError containing {marker!r}")


def test_update_image_contract() -> None:
    hard._strict_update_name("JARNSEN-TRACKER-Build-167.update.bin")
    expect_error(lambda: hard._strict_update_name("tracker.factory.bin"), ".update.bin")
    expect_error(lambda: hard._strict_update_name("tracker-webflasher.update.bin"), "Factory-/Webflasher")
    expect_error(lambda: hard._strict_update_name("tracker.bin"), ".update.bin")

    good = {
        "schema": 1,
        "device": series.DEVICES["TRACKER"]["device"],
        "firmware_asset": "tracker.update.bin",
        "firmware_size": 123,
        "firmware_sha256": "a" * 64,
        "ota_partition_offset": hard.OTA_LOADER_OFFSET,
    }
    hard._validate_manifest_contract(good, "TRACKER")
    wrong = dict(good, device=series.DEVICES["V3"]["device"])
    expect_error(lambda: hard._validate_manifest_contract(wrong, "TRACKER"), "Hardware")
    no_hash = dict(good, firmware_sha256="")
    expect_error(lambda: hard._validate_manifest_contract(no_hash, "TRACKER"), "SHA-256")


def test_runtime_wiring() -> None:
    entry = (ROOT / "JARNSEN_FRAMEWORK7_SERVICE_TOOL_V31.py").read_text(encoding="utf-8")
    required_imports = (
        "from JARNSEN_FRAMEWORK7_SERIES_HARDENING import install_series_hardening",
        "from JARNSEN_FRAMEWORK7_FLASH_HARDENING import install_flash_hardening",
        "from JARNSEN_FRAMEWORK7_FEATURE_HARDENING import install_feature_hardening",
    )
    for marker in required_imports:
        if entry.count(marker) != 2:
            raise AssertionError(f"runtime import must exist in both start paths: {marker}")
    for marker in (
        "install_series_hardening(base.LegacyBridge, base.ApiHandler)",
        "install_flash_hardening(base.LegacyBridge, base.ApiHandler)",
        "install_feature_hardening(base.LegacyBridge, base.ApiHandler)",
    ):
        if entry.count(marker) != 2:
            raise AssertionError(f"runtime install must exist in both start paths: {marker}")


def test_feature_contract() -> None:
    source = (ROOT / "JARNSEN_FRAMEWORK7_FEATURE_HARDENING.py").read_text(encoding="utf-8")
    required = (
        "_prepare_profile_provision_bundle(self, payload)",
        "self.tool.batch_ota_v2133()",
        "_prefetch_ble_bundles(self.tool, [node_id])",
        "_prefetch_ble_bundles(self.tool, node_ids)",
        '"profile_provision_hardware_guard"',
        '"profile_provision_preflight_bundle"',
        '"ble_ota_source_preflight"',
        '"ble_recovery_signature"',
        "MAX_FEATURE_REQUEST",
        "Feature-Anforderung muss ein JSON-Objekt sein",
        '"/api/action"',
        '"/api/profile/action"',
        '"/api/profile/section"',
        '"/api/live/action"',
        '"/api/radio-authorization"',
        "self.bridge.action(payload)",
        "self.bridge.save_radio_authorization(payload)",
    )
    for marker in required:
        if marker not in source:
            raise AssertionError(f"feature hardening contract missing: {marker}")
    if "batch_ota_v2133([node_id])" in source:
        raise AssertionError("legacy BLE recovery signature regression returned")
    preflight = source.index("_prepare_profile_provision_bundle(self, payload)")
    delegate = source.index("previous_profile_action(self, guarded)")
    if preflight >= delegate:
        raise AssertionError("profile provisioning delegates before safety preflight")


def test_state_contract() -> None:
    compat = (ROOT / "JARNSEN_FRAMEWORK7_LEGACY_COMPAT.py").read_text(encoding="utf-8")
    if "_CallableGetAdapter" in compat or "_guard_callable_mappings" in compat:
        raise AssertionError("legacy callable mapping adapter/guard still exists in built source")
    if compat.count("enforce_service_state_contracts(self.tool)") < 2:
        raise AssertionError("strict state ownership is not enforced at bridge init and state collection")


def test_build_smoke_contract() -> None:
    build = (ROOT / "ci" / "build_framework7_service_tool.ps1").read_text(encoding="utf-8")
    for marker in (
        "JARNSEN_FRAMEWORK7_SERIES_HARDENING.py",
        "JARNSEN_FRAMEWORK7_FLASH_HARDENING.py",
        "JARNSEN_FRAMEWORK7_FEATURE_HARDENING.py",
        "series_pre_destructive_bundle",
        "serial_flash_hardware_guard",
        "profile_provision_hardware_guard",
        "ble_ota_source_preflight",
        "ble_recovery_signature",
    ):
        if marker not in build:
            raise AssertionError(f"packaged smoke contract missing: {marker}")


def main() -> None:
    test_update_image_contract()
    test_runtime_wiring()
    test_feature_contract()
    test_state_contract()
    test_build_smoke_contract()
    print("Framework7 destructive-action hardening contracts OK")


def _run_logged() -> None:
    log_dir = ROOT.parent / "ci-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "framework7-hardening-contracts.log"
    try:
        main()
    except BaseException:
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        raise
    log_path.write_text("Framework7 destructive-action hardening contracts OK\n", encoding="utf-8")


if __name__ == "__main__":
    _run_logged()
