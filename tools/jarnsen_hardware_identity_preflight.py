#!/usr/bin/env python3
"""Static contracts for persistent JARNSEN physical-hardware identity."""

from __future__ import annotations

import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


class IdentityFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise IdentityFailure(message)


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise IdentityFailure(f"required file missing: {rel}")
    return path.read_text(encoding="utf-8")


def parse_num(value: str) -> int:
    return int(value.strip(), 0)


def read_partition(rel: str) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    lines = [line for line in read(rel).splitlines() if line.strip() and not line.lstrip().startswith("#")]
    for row in csv.reader(lines):
        require(len(row) >= 5, f"{rel}: malformed partition row: {row}")
        name = row[0].strip()
        result[name] = (parse_num(row[3]), parse_num(row[4]))
    return result


def check_partition(rel: str, marker_offset: int, flash_end: int) -> None:
    parts = read_partition(rel)
    require("jarnsen_hw" in parts, f"{rel}: dedicated jarnsen_hw partition missing")
    offset, size = parts["jarnsen_hw"]
    require(offset == marker_offset, f"{rel}: jarnsen_hw offset 0x{offset:x}, expected 0x{marker_offset:x}")
    require(size == 0x1000, f"{rel}: jarnsen_hw must be exactly one 4 KB sector")
    require(offset + size == flash_end, f"{rel}: jarnsen_hw must occupy the physical final flash sector")
    for name, (other_offset, other_size) in parts.items():
        if name == "jarnsen_hw" or other_size == 0:
            continue
        require(other_offset + other_size <= offset or other_offset >= offset + size,
                f"{rel}: partition {name} overlaps jarnsen_hw")


def main() -> int:
    identity = read("src/jarnsen/core/service/JarnsenHardwareIdentity.cpp")
    header = read("src/jarnsen/core/service/JarnsenHardwareIdentity.h")
    serial = read("src/SerialConsole.cpp")
    runtime = read("src/jarnsen/core/runtime/JarnsenRuntimePolicy.cpp")
    linker = read("src/platform/nrf52/nrf52840_s140_v7.ld")
    profiles = read("src/jarnsen/hardware/JarnsenHardwareProfiles.h")
    packager = read(".buildkite/package-jarnsen-firmware.py")

    check_partition("partition-table.csv", 0x3FF000, 0x400000)
    check_partition("default_8MB.csv", 0x7FF000, 0x800000)
    check_partition("default_16MB.csv", 0xFFF000, 0x1000000)

    require("0xE9000 - 0x27000" in linker, "Wio L1 linker does not reserve the 0xE9000 hardware-id page")
    require("0xEA000-0xED000" in linker, "Wio L1 warm-node-store region changed unexpectedly")
    require("WIO_HARDWARE_ID_ADDRESS = 0x000E9000U" in identity, "Wio L1 raw hardware-id address missing")
    require("flash_nrf5x_write(WIO_HARDWARE_ID_ADDRESS" in identity, "Wio L1 identity is not written to raw flash")
    require("flash_nrf5x_flush();" in identity, "Wio L1 identity write is not flushed")

    require("ESP.getFlashChipSize()" in identity, "ESP32 identity does not derive the marker from physical flash size")
    require("flashBytes - HARDWARE_ID_SECTOR_SIZE" in identity, "ESP32 marker is not located at physical flash end")
    require("esp_flash_write(esp_flash_default_chip" in identity, "ESP32 identity is not written through raw flash API")
    require("esp_flash_erase_region" not in identity, "normal hardware-id initialization must not erase a sector")
    require("prefs.putBytes" not in identity, "normal ESP32 hardware identity must not be persisted in Preferences")
    require("FSCom.open(LEGACY_NRF52_FILE, FILE_O_WRITE" not in identity, "normal Wio identity must not be written to LittleFS")

    require("ESP.getEfuseMac()" in identity, "ESP32 read-only chip identity missing")
    require("NRF_FICR->DEVICEID" in identity, "Wio/nRF52840 read-only chip identity missing")
    for forbidden in ("esp_efuse_write", "esp_efuse_burn", "esp_efuse_batch_write", "NRF_UICR->"):
        require(forbidden not in identity, f"forbidden permanent-ID write primitive present: {forbidden}")

    for key in ("heltec_tracker_v1_1", "heltec_v3", "heltec_v4", "seeed_wio_tracker_l1", "tbeam", "tbeam_supreme"):
        require(f'"{key}"' in identity, f"stable board key missing: {key}")

    for macro in ("HELTEC_TRACKER_V1_1", "HELTEC_V3", "HELTEC_V4", "SEEED_WIO_TRACKER_L1", "TBEAM_V10", "LILYGO_TBEAM_S3_CORE"):
        require(macro in profiles, f"Unified hardware profile missing target macro: {macro}")

    require("hardwareIdentityInit();" in runtime, "hardware identity is not initialized during common JARNSEN runtime startup")
    require('strcmp(command, "JARNSEN_TOOL_HW_INFO") == 0' in serial, "JARNSEN_TOOL_HW_INFO command missing")
    require("JARNSEN_HW_INFO schema=%u board=%s chip=%016llX" in identity, "machine-readable HW_INFO response contract changed")
    require("identity.storedKind != identity.firmwareKind" in identity, "firmware/hardware mismatch comparison missing")
    require("writeDedicatedFirstRecord(legacy)" in identity, "legacy alpha hardware identity is not migrated safely")
    require("physical flash does not match firmware target; provisioning blocked" in identity,
            "obvious wrong-flash-size first provisioning is not blocked")

    require("jarnsen_hw" in packager, "packager does not validate/preserve the dedicated ESP32 hardware-id partition")
    require("hardware_identity" in packager, "package manifest does not describe hardware identity preservation")
    require("hardwareIdentityFormat" in header, "public HW_INFO formatter missing")
    require("JARNSEN_TOOL_HW_SET" not in serial, "unsafe arbitrary hardware relabel command exposed")

    print("JARNSEN hardware identity audit: PASS")
    print("- dedicated final-sector ESP32 marker reserved for 4/8/16 MB layouts")
    print("- Wio Tracker L1 has a dedicated raw 4 KB page below the warm-node store")
    print("- chip identity is read-only; no eFuse/UICR write primitive is present")
    print("- valid identity remains immutable across firmware-target mismatch")
    print("- legacy alpha identity migrates without relabeling")
    print("- Service Tool HW_INFO contract covers all six supported boards")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except IdentityFailure as exc:
        print(f"JARNSEN hardware identity audit: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
