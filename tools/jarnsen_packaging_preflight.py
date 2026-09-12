#!/usr/bin/env python3
"""Static/deterministic packaging contract for JARNSEN firmware images."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGER = ROOT / ".buildkite" / "package-jarnsen-firmware.py"
RUNNER = ROOT / ".buildkite" / "run-unified-build.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "build-jarn-mesh-unified-core.yml"


class PackagingFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PackagingFailure(message)


def expect_exit(callable_obj, expected_text: str) -> None:
    try:
        callable_obj()
    except SystemExit as exc:
        require(expected_text in str(exc), f"Expected failure containing {expected_text!r}, got {exc!r}")
        return
    raise PackagingFailure(f"Expected packaging failure containing {expected_text!r}")


def make_dual_slot_partitions(app0: int, slot_size: int, data_size: int) -> list[dict[str, int | str]]:
    app1 = app0 + slot_size
    return [
        {"type": 0x00, "subtype": 0x10, "offset": app0, "size": slot_size, "label": "app0"},
        {"type": 0x00, "subtype": 0x11, "offset": app1, "size": slot_size, "label": "app1"},
        {"type": 0x01, "subtype": 0x82, "offset": app1 + slot_size, "size": data_size, "label": "spiffs"},
    ]


def validate_dual_slot_layout(module, name: str, app0: int, slot_size: int, data_size: int) -> None:
    app = bytes([0xE9]) + f"JARNSEN-{name}-WEBFLASHER-CONTRACT".encode("ascii")
    partitions = make_dual_slot_partitions(app0, slot_size, data_size)
    payload = module.build_meshtastic_webflasher(app, partitions)
    require(len(payload) == 2 * slot_size, f"{name}: custom BIN must span exactly both OTA slots")
    require(payload[: len(app)] == app, f"{name}: app0 payload mismatch")
    require(payload[slot_size : slot_size + len(app)] == app, f"{name}: app1 payload mismatch")
    require(payload[0] == 0xE9 and payload[slot_size] == 0xE9, f"{name}: both OTA slots need ESP image headers")


def main() -> int:
    spec = importlib.util.spec_from_file_location("jarnsen_packager", PACKAGER)
    if spec is None or spec.loader is None:
        raise PackagingFailure("cannot load packaging module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Real JARNSEN dual-slot classes used by the supported ESP32-S3 boards.
    validate_dual_slot_layout(module, "8MB", app0=0x10000, slot_size=0x330000, data_size=0x180000)
    validate_dual_slot_layout(module, "16MB", app0=0x10000, slot_size=0x640000, data_size=0x370000)

    # A custom-upload image must never silently accept firmware larger than a slot.
    small_slot = 0x2000
    oversized_app = bytes([0xE9]) + (b"X" * small_slot)
    oversized_partitions = make_dual_slot_partitions(0x10000, small_slot, 0x1000)
    expect_exit(
        lambda: module.build_meshtastic_webflasher(oversized_app, oversized_partitions),
        "exceeds OTA slot sizes",
    )

    # Any third partition inside the upload span must be rejected, even if the app itself fits.
    overlap_app = bytes([0xE9]) + b"JARNSEN-OVERLAP-CONTRACT"
    overlap_partitions = make_dual_slot_partitions(0x10000, 0x4000, 0x1000)
    overlap_partitions.append(
        {"type": 0x01, "subtype": 0x02, "offset": 0x12000, "size": 0x1000, "label": "forbidden-overlap"}
    )
    expect_exit(
        lambda: module.build_meshtastic_webflasher(overlap_app, overlap_partitions),
        "overlaps partition forbidden-overlap",
    )

    packager_text = PACKAGER.read_text(encoding="utf-8")
    runner_text = RUNNER.read_text(encoding="utf-8")
    workflow_text = WORKFLOW.read_text(encoding="utf-8")

    require('f"{prefix}-meshtastic-webflasher.bin"' in packager_text, "Meshtastic Web Flasher artifact is not explicitly named")
    require('f"{prefix}-webflasher.bin"' not in packager_text, "Ambiguous legacy webflasher artifact name is still emitted")
    require('bytearray(factory)' not in packager_text, "Meshtastic Web Flasher payload must not be based on the absolute factory image")
    require('-meshtastic-webflasher.bin' in workflow_text, "Release gate does not require the explicitly named Meshtastic Web Flasher BIN")
    require('release-assets/${prefix}-webflasher.bin' not in workflow_text, "Release gate still accepts the ambiguous legacy webflasher filename")
    require('buildkite-agent' not in runner_text, "Legacy external artifact uploader is still active in Unified Core runner")
    require('JARNSEN_TEST_ARTIFACT' not in runner_text, "Legacy test-artifact packaging path is still active in Unified Core runner")
    require('BUILDKITE_BUILD_NUMBER' not in runner_text, "Legacy build-number environment variable is still active in Unified Core runner")

    print("JARNSEN packaging audit: PASS")
    print("- 8 MB and 16 MB dual-slot Web Flasher layouts validated")
    print("- oversized applications are rejected")
    print("- partition overlap inside the upload span is rejected")
    print("- Meshtastic Web Flasher BIN is app0-relative, not factory/0x0000-relative")
    print("- artifact/release naming is explicit: meshtastic-webflasher.bin")
    print("- Unified Core runner contains no active legacy artifact-upload path")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PackagingFailure as exc:
        print(f"JARNSEN packaging audit: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
