#!/usr/bin/env python3
"""Static/deterministic packaging contract for Meshtastic Web Flasher images."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGER = ROOT / ".buildkite" / "package-jarnsen-firmware.py"
WORKFLOW = ROOT / ".github" / "workflows" / "build-jarn-mesh-unified-core.yml"


class PackagingFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PackagingFailure(message)


def main() -> int:
    spec = importlib.util.spec_from_file_location("jarnsen_packager", PACKAGER)
    if spec is None or spec.loader is None:
        raise PackagingFailure("cannot load packaging module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    app = bytes([0xE9]) + b"JARNSEN-WEBFLASHER-CONTRACT"
    app0 = 0x10000
    slot_size = 0x330000
    app1 = app0 + slot_size
    partitions = [
        {"type": 0x00, "subtype": 0x10, "offset": app0, "size": slot_size, "label": "app0"},
        {"type": 0x00, "subtype": 0x11, "offset": app1, "size": slot_size, "label": "app1"},
        {"type": 0x01, "subtype": 0x82, "offset": app1 + slot_size, "size": 0x180000, "label": "spiffs"},
    ]

    payload = module.build_meshtastic_webflasher(app, partitions)
    require(len(payload) == 2 * slot_size, "Meshtastic custom BIN must be relative to app0 and span exactly both OTA slots")
    require(payload[: len(app)] == app, "Meshtastic custom BIN must start with the application at file offset 0")
    require(payload[slot_size : slot_size + len(app)] == app, "Meshtastic custom BIN must populate OTA slot 1 at the relative slot offset")
    require(payload[0] == 0xE9 and payload[slot_size] == 0xE9, "Both relative OTA slots must carry an ESP application header")

    packager_text = PACKAGER.read_text(encoding="utf-8")
    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    require('f"{prefix}-meshtastic-webflasher.bin"' in packager_text, "Meshtastic Web Flasher artifact is not explicitly named")
    require('f"{prefix}-webflasher.bin"' not in packager_text, "Ambiguous legacy webflasher artifact name is still emitted")
    require('bytearray(factory)' not in packager_text, "Meshtastic Web Flasher payload must not be based on the absolute factory image")
    require('-meshtastic-webflasher.bin' in workflow_text, "Release gate does not require the explicitly named Meshtastic Web Flasher BIN")
    require('release-assets/${prefix}-webflasher.bin' not in workflow_text, "Release gate still accepts the ambiguous legacy webflasher filename")

    print("JARNSEN packaging audit: PASS")
    print("- Meshtastic Web Flasher BIN is app0-relative, not factory/0x0000-relative")
    print("- both OTA slots are populated without touching bootloader/NVS/partition-table space")
    print("- artifact/release naming is explicit: meshtastic-webflasher.bin")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PackagingFailure as exc:
        print(f"JARNSEN packaging audit: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
