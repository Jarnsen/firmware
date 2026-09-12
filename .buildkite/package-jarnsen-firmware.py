#!/usr/bin/env python3
"""Collect and validate one Unified Core firmware package.

ESP32 application offsets are derived from the generated partition table instead
of assuming 0x10000. The dedicated jarnsen_hw partition is validated and kept
outside all normal update/factory payloads so physical hardware identity survives
firmware replacement. For boards that support custom uploads in the Meshtastic
Web Flasher, the dedicated image is relative to the first OTA application slot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

HW_ID_SIZE = 0x1000
WIO_HW_ID_ADDRESS = 0xE9000


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--environment", required=True)
    p.add_argument("--board", required=True)
    p.add_argument("--artifact-label", required=True)
    p.add_argument("--artifact-kind", choices=("esp32", "uf2"), required=True)
    p.add_argument("--webflasher", choices=("true", "false"), required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--build", required=True, type=int)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--output", default="firmware-artifact")
    return p.parse_args()


def first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


def find_application(build_dir: Path, env: str) -> Path:
    candidates = sorted(
        p
        for p in build_dir.glob(f"firmware-{env}-*.bin")
        if not p.name.endswith(".factory.bin")
        and not p.name.endswith(".webflasher.bin")
        and not p.name.endswith(".meshtastic-webflasher.bin")
    )
    if candidates:
        return candidates[0]
    fallback = first_existing([build_dir / "firmware.bin"])
    if fallback:
        return fallback
    raise SystemExit(f"No application BIN found in {build_dir}")


def find_factory(build_dir: Path, env: str) -> Path:
    candidates = sorted(build_dir.glob(f"firmware-{env}-*.factory.bin"))
    if candidates:
        return candidates[0]
    fallback = first_existing([build_dir / "firmware.factory.bin"])
    if fallback:
        return fallback
    raise SystemExit(f"Factory BIN required for ESP32 package in {build_dir}")


def parse_partition_table(raw_table: bytes) -> list[dict[str, int | str]]:
    entry_size = 32
    table_limit = min(len(raw_table), 0x1000)
    if raw_table[:2] != b"\xaa\x50":
        raise SystemExit("Partition-table magic invalid")
    partitions: list[dict[str, int | str]] = []
    for pos in range(0, table_limit, entry_size):
        raw = raw_table[pos : pos + entry_size]
        if len(raw) < entry_size:
            break
        magic = struct.unpack_from("<H", raw, 0)[0]
        if magic == 0xFFFF:
            break
        if magic == 0xEBEB:
            continue
        if magic != 0x50AA:
            raise SystemExit(f"Invalid partition entry magic 0x{magic:04x} at table offset 0x{pos:x}")
        p_type = raw[2]
        subtype = raw[3]
        offset, size = struct.unpack_from("<II", raw, 4)
        label = raw[12:28].split(b"\x00", 1)[0].decode("ascii", errors="replace")
        partitions.append({"type": p_type, "subtype": subtype, "offset": offset, "size": size, "label": label})
    if not partitions:
        raise SystemExit("Partition table contains no entries")
    return partitions


def load_partitions(build_dir: Path, factory: bytes) -> list[dict[str, int | str]]:
    generated = first_existing([build_dir / "partitions.bin", build_dir / "partition-table.bin"])
    if generated:
        print(f"Using generated partition table: {generated}")
        return parse_partition_table(generated.read_bytes())
    table_offset = 0x8000
    if len(factory) < table_offset + 2:
        raise SystemExit("Factory image too small to contain partition table")
    print("Generated partitions.bin missing; using partition table embedded at 0x8000")
    return parse_partition_table(factory[table_offset : table_offset + 0x1000])


def find_factory_app_partition(app: bytes, factory: bytes, partitions: list[dict[str, int | str]]) -> dict[str, int | str]:
    candidates = [
        p
        for p in partitions
        if p["type"] == 0x00
        and int(p["size"]) >= len(app)
        and len(factory) >= int(p["offset"]) + len(app)
    ]
    matches = [p for p in candidates if factory[int(p["offset"]) : int(p["offset"]) + len(app)] == app]
    if not matches:
        summary = ", ".join(
            f"{p['label'] or '?'}:sub=0x{int(p['subtype']):02x}@0x{int(p['offset']):x}+0x{int(p['size']):x}"
            for p in candidates
        ) or "none"
        raise SystemExit(
            "Factory application payload does not match update image in any app partition; "
            f"candidates: {summary}"
        )
    return matches[0]


def find_partition(partitions: list[dict[str, int | str]], label: str) -> dict[str, int | str] | None:
    wanted = label.lower()
    for part in partitions:
        if str(part["label"]).lower() == wanted:
            return part
    return None


def validate_hardware_identity_partition(
    partitions: list[dict[str, int | str]], factory: bytes
) -> dict[str, int | str]:
    marker = find_partition(partitions, "jarnsen_hw")
    if marker is None:
        raise SystemExit("Dedicated jarnsen_hw partition missing from ESP32 partition table")
    offset, size = int(marker["offset"]), int(marker["size"])
    if marker["type"] != 0x01 or size != HW_ID_SIZE:
        raise SystemExit(
            f"Invalid jarnsen_hw partition: type=0x{int(marker['type']):02x} offset=0x{offset:x} size=0x{size:x}"
        )
    highest_end = max(int(p["offset"]) + int(p["size"]) for p in partitions if int(p["size"]) > 0)
    if offset + size != highest_end:
        raise SystemExit(
            f"jarnsen_hw must be the final physical partition: marker_end=0x{offset + size:x} layout_end=0x{highest_end:x}"
        )
    if len(factory) > offset:
        raise SystemExit(
            f"Factory image ({len(factory)} bytes) reaches dedicated jarnsen_hw marker at 0x{offset:x}; identity would be overwritten"
        )
    print(f"Validated persistent hardware identity partition: offset=0x{offset:x} size=0x{size:x}; factory preserves it")
    return marker


def find_ota(
    partitions: list[dict[str, int | str]], subtype: int, fallback_label: str
) -> dict[str, int | str] | None:
    for p in partitions:
        if p["type"] == 0x00 and p["subtype"] == subtype:
            return p
    for p in partitions:
        if p["type"] == 0x00 and str(p["label"]).lower() == fallback_label:
            return p
    return None


def build_meshtastic_webflasher(app: bytes, partitions: list[dict[str, int | str]]) -> bytes:
    """Build the custom BIN expected by the Meshtastic Web Flasher."""
    ota0 = find_ota(partitions, 0x10, "app0")
    ota1 = find_ota(partitions, 0x11, "app1")
    if ota0 is None or ota1 is None:
        summary = ", ".join(
            f"{p['label'] or '?'}:type=0x{int(p['type']):02x}/sub=0x{int(p['subtype']):02x}@0x{int(p['offset']):x}+0x{int(p['size']):x}"
            for p in partitions
        )
        raise SystemExit(f"Compatible OTA0/OTA1 partitions not found: {summary}")

    app0, app1 = int(ota0["offset"]), int(ota1["offset"])
    size0, size1 = int(ota0["size"]), int(ota1["size"])
    if app0 >= app1:
        raise SystemExit(f"Invalid OTA slot order: app0=0x{app0:x}, app1=0x{app1:x}")
    if len(app) > size0 or len(app) > size1:
        raise SystemExit(
            f"Application image ({len(app)} bytes) exceeds OTA slot sizes 0x{size0:x}/0x{size1:x}"
        )

    upload_base = app0
    upload_end = app1 + size1
    for part in partitions:
        if part is ota0 or part is ota1 or int(part["size"]) == 0:
            continue
        part_start = int(part["offset"])
        part_end = part_start + int(part["size"])
        if part_start < upload_end and part_end > upload_base:
            raise SystemExit(
                f"Meshtastic Web Flasher span 0x{upload_base:x}-0x{upload_end:x} overlaps partition "
                f"{part['label'] or '?'} at 0x{part_start:x}-0x{part_end:x}"
            )

    required_size = upload_end - upload_base
    slot1_offset = app1 - upload_base
    image = bytearray(b"\xff" * required_size)
    image[0 : len(app)] = app
    image[slot1_offset : slot1_offset + len(app)] = app

    if image[0] != 0xE9 or image[slot1_offset] != 0xE9:
        raise SystemExit("Meshtastic Web Flasher image does not start both OTA slots with an ESP image header")

    print(
        "Built Meshtastic Web Flasher custom image: "
        f"{len(image)} bytes; upload_base=0x{upload_base:x}; "
        f"app0=file+0x0/0x{size0:x}; app1=file+0x{slot1_offset:x}/0x{size1:x}"
    )
    return bytes(image)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    args = parse_args()
    build_dir = Path(".pio") / "build" / args.environment
    if not build_dir.is_dir():
        raise SystemExit(f"Build directory does not exist: {build_dir}")
    out = Path(args.output)
    if out.exists():
        for child in out.iterdir():
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                import shutil
                shutil.rmtree(child)
    out.mkdir(parents=True, exist_ok=True)
    prefix = f"JARNSEN-MESH-{args.artifact_label}-{args.version}-Build-{args.build}"
    hardware_identity: dict[str, int | str | bool]

    if args.artifact_kind == "uf2":
        uf2s = sorted(build_dir.glob("firmware*.uf2"))
        if not uf2s:
            raise SystemExit(f"No UF2 firmware found in {build_dir}")
        (out / f"{prefix}-firmware.uf2").write_bytes(uf2s[0].read_bytes())
        variants = ["uf2"]
        hardware_identity = {
            "storage": "nrf52840_raw_page",
            "address": WIO_HW_ID_ADDRESS,
            "size": HW_ID_SIZE,
            "preserved_by_normal_firmware": True,
        }
    else:
        app_path = find_application(build_dir, args.environment)
        factory_path = find_factory(build_dir, args.environment)
        app, factory = app_path.read_bytes(), factory_path.read_bytes()
        if not app or app[0] != 0xE9:
            raise SystemExit(f"Invalid ESP32 application image: {app_path}")
        partitions = load_partitions(build_dir, factory)
        marker = validate_hardware_identity_partition(partitions, factory)
        app_part = find_factory_app_partition(app, factory, partitions)
        app_offset = int(app_part["offset"])
        if factory[app_offset] != 0xE9:
            raise SystemExit(f"Factory application header invalid at 0x{app_offset:x}: {factory_path}")
        print(
            f"Validated ESP32 application image: {len(app)} bytes; "
            f"partition={app_part['label'] or '?'} offset=0x{app_offset:x} size=0x{int(app_part['size']):x}"
        )
        (out / f"{prefix}-update.bin").write_bytes(app)
        (out / f"{prefix}-factory.bin").write_bytes(factory)
        variants = ["update", "factory"]
        if args.webflasher == "true":
            payload = build_meshtastic_webflasher(app, partitions)
            (out / f"{prefix}-meshtastic-webflasher.bin").write_bytes(payload)
            variants.append("meshtastic-webflasher")
        hardware_identity = {
            "storage": "esp32_jarnsen_hw_partition",
            "address": int(marker["offset"]),
            "size": int(marker["size"]),
            "preserved_by_normal_firmware": True,
        }

    manifest = {
        "schema": 1,
        "product": "JARNSEN-MESH",
        "version": args.version,
        "board": args.board,
        "platformio_environment": args.environment,
        "build": args.build,
        "source_sha": args.source_sha,
        "variants": variants,
        "hardware_identity": hardware_identity,
    }
    (out / f"{prefix}-package-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    readme = f"""JARNSEN-MESH {args.version}
Board: {args.board}
PlatformIO environment: {args.environment}
Build: {args.build}
Source SHA: {args.source_sha}

This package was compiled from the shared JARNSEN-MESH Unified Core.
ESP32 packages contain update.bin and factory.bin. Boards with a verified
dual-slot layout additionally contain meshtastic-webflasher.bin.

Flash policy:
- update.bin: application/OTA image for an existing compatible partition layout.
- factory.bin: absolute image starting at 0x000000; it intentionally ends before
  the dedicated persistent physical-hardware identity storage.
- meshtastic-webflasher.bin: custom firmware for the Meshtastic Web Flasher only;
  byte 0 is relative to the first OTA app partition and must not be flashed at 0x000000.
- normal update/factory/Web-Flasher operations preserve the JARNSEN physical-hardware marker.
- an explicit whole-chip erase intentionally removes the marker and requires re-provisioning.

All ESP32 application offsets are derived from the generated partition table;
no board-specific application offset is hard-coded. The Wio Tracker L1 keeps
its native UF2 image and a dedicated raw 4 KB identity page outside the app range.
"""
    (out / f"{prefix}-README.txt").write_text(readme, encoding="utf-8")
    checksum_path = out / f"{prefix}-SHA256SUMS.txt"
    checksum_lines = [
        f"{sha256(path)}  {path.name}"
        for path in sorted(p for p in out.iterdir() if p.is_file() and p != checksum_path)
    ]
    checksum_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    print(f"Packaged {args.board} -> {out}")
    for path in sorted(out.iterdir()):
        if path.is_file():
            print(f"  {path.name}: {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
