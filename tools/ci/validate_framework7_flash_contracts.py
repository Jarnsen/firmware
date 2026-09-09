"""Regression tests for Framework7 Series/serial flash safety contracts."""
from __future__ import annotations

import hashlib
import pathlib
import sys
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import JARNSEN_FRAMEWORK7_SERIES as series
import JARNSEN_FRAMEWORK7_SERIES_HARDENING as hard
import JARNSEN_FRAMEWORK7_FLASH_HARDENING as flash


def expect_runtime(label: str, callback) -> None:
    try:
        callback()
    except RuntimeError:
        return
    raise AssertionError(f"{label}: RuntimeError expected")


def valid_image(seed: bytes = b"app") -> bytes:
    return b"\xe9" + seed * 100


def manifest(code: str, firmware: bytes) -> dict[str, object]:
    return {
        "schema": 1,
        "device": series.DEVICES[code]["device"],
        "source_sha": "a" * 40,
        "firmware_asset": f"test-{code.lower()}.update.bin",
        "firmware_size": len(firmware),
        "firmware_sha256": hashlib.sha256(firmware).hexdigest(),
        "ota_partition_offset": "0x340000",
    }


def test_update_image_gate() -> None:
    hard._strict_update_name("tracker.update.bin")
    expect_runtime("factory image", lambda: hard._strict_update_name("tracker.factory.bin"))
    expect_runtime("webflasher image", lambda: hard._strict_update_name("tracker-meshtastic-webflasher.bin"))
    expect_runtime("generic bin", lambda: hard._strict_update_name("tracker.bin"))


def test_manifest_contract() -> None:
    fw = valid_image()
    good = manifest("TRACKER", fw)
    hard._validate_manifest_contract(good, "TRACKER")
    wrong = dict(good)
    wrong["device"] = series.DEVICES["V3"]["device"]
    expect_runtime("wrong manifest device", lambda: hard._validate_manifest_contract(wrong, "TRACKER"))
    factory = dict(good)
    factory["firmware_asset"] = "tracker.factory.bin"
    expect_runtime("factory manifest asset", lambda: hard._validate_manifest_contract(factory, "TRACKER"))


def test_virgin_profile_fallback_and_mismatch() -> None:
    fw = valid_image(b"tracker")
    loader = b"\xe9loader"
    good_manifest = manifest("TRACKER", fw)
    old_detect = hard._detect_usb_hardware
    old_resolve = hard._resolve_bundle
    old_loader_hash = hard.OTA_LOADER_SHA256
    hard._detect_usb_hardware = lambda _tool, _port: ""
    hard._resolve_bundle = lambda _tool, _code, _ctx: ((fw, loader, good_manifest), "test")
    hard.OTA_LOADER_SHA256 = hashlib.sha256(loader).hexdigest()
    try:
        tool = SimpleNamespace()
        tool.config_profile_store = {"profiles": [{"source_hw": "HELTEC_TRACKER_V1.1"}]}
        tool._device_code_from_hw_text = lambda text: "TRACKER" if "TRACKER" in text.upper() else ""
        tool._framework7_series_request_context = {"profile_slot": 0, "source": "local"}
        code = hard._preflight_and_prefetch(tool, "COM7", "AUTO")
        assert code == "TRACKER"
        assert tool._framework7_series_request_context["virgin_profile_fallback"] is True
        assert tool._framework7_series_prefetched_bundle["device_code"] == "TRACKER"
        expect_runtime(
            "explicit hardware contradicts profile",
            lambda: hard._preflight_and_prefetch(tool, "COM7", "V3"),
        )
    finally:
        hard._detect_usb_hardware = old_detect
        hard._resolve_bundle = old_resolve
        hard.OTA_LOADER_SHA256 = old_loader_hash


def test_physical_board_mismatch() -> None:
    old_detect = hard._detect_usb_hardware
    hard._detect_usb_hardware = lambda _tool, _port: "V3"
    try:
        tool = SimpleNamespace()
        tool.config_profile_store = {"profiles": [{"source_hw": "HELTEC_V3_REPEATER"}]}
        tool._device_code_from_hw_text = lambda text: "V3" if "V3" in text.upper() else ""
        tool._framework7_series_request_context = {"profile_slot": 0, "source": "local"}
        expect_runtime(
            "physical board mismatch",
            lambda: hard._preflight_and_prefetch(tool, "COM8", "TRACKER"),
        )
    finally:
        hard._detect_usb_hardware = old_detect


def test_prefetched_bundle_wrapper_does_not_redownload() -> None:
    fw = valid_image(b"cached")
    loader = b"\xe9loader"
    mf = manifest("TRACKER", fw)
    calls: list[str] = []

    class Tool:
        pass

    tool = Tool()
    tool._download_serial_bundle = lambda code: calls.append(code) or (_ for _ in ()).throw(AssertionError("unexpected redownload"))
    tool._framework7_series_bundle_override = {"source": "local", "device_code": "TRACKER"}
    tool._framework7_series_prefetched_bundle = {
        "device_code": "TRACKER",
        "source": "local",
        "bundle": (fw, loader, mf),
        "label": "cached",
    }
    tool._framework7_series_job = {}
    hard._install_prefetch_bundle_wrapper(tool)
    got = tool._download_serial_bundle("TRACKER")
    assert got[0] == fw and got[1] == loader
    assert not calls
    assert tool._framework7_series_bundle_override is None


def test_generic_one_shot_bundle_cache() -> None:
    fw = valid_image(b"generic")
    loader = b"\xe9loader"
    mf = manifest("TRACKER", fw)
    fallback_calls: list[str] = []

    class Tool:
        pass

    tool = Tool()
    original = lambda code: fallback_calls.append(code) or (b"fallback", b"fallback", {})
    tool._download_serial_bundle = original
    flash._install_one_shot_bundle(tool, "TRACKER", (fw, loader, mf))
    first = tool._download_serial_bundle("TRACKER")
    assert first[0] == fw
    assert tool._download_serial_bundle is original
    assert not fallback_calls


def test_generic_bundle_validation() -> None:
    fw = valid_image(b"generic-validate")
    loader = b"\xe9loader"
    mf = manifest("TRACKER", fw)
    old_hash = flash.OTA_LOADER_SHA256
    flash.OTA_LOADER_SHA256 = hashlib.sha256(loader).hexdigest()
    try:
        checked = flash._validate_bundle((fw, loader, mf), "TRACKER")
        assert checked[0] == fw
        bad = dict(mf)
        bad["firmware_asset"] = "tracker.factory.bin"
        expect_runtime("generic factory reject", lambda: flash._validate_bundle((fw, loader, bad), "TRACKER"))
    finally:
        flash.OTA_LOADER_SHA256 = old_hash


def main() -> None:
    tests = [
        test_update_image_gate,
        test_manifest_contract,
        test_virgin_profile_fallback_and_mismatch,
        test_physical_board_mismatch,
        test_prefetched_bundle_wrapper_does_not_redownload,
        test_generic_one_shot_bundle_cache,
        test_generic_bundle_validation,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"Framework7 flash contracts OK ({len(tests)} tests)")


if __name__ == "__main__":
    main()
