#!/usr/bin/env python3
"""Collect and validate one Unified Core firmware package.

This intentionally derives ESP32 application offsets from the generated
partition table instead of assuming 0x10000. That is required for the current
V3/V4/Tracker/T-Beam Supreme OTA layouts and prevents the Build 141 packaging
regression from returning.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path


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
        if not p.name.endswith(".factory.bin") and not p.name.endswith(".webflasher.bin")
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
            # ESP-IDF appends an MD5 checksum record to generated binary
            # partition tables. It is metadata, not a flash partition.
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
    candidates = [p for p in partitions if p["type"] == 0x00 and int(p["size"]) >= len(app) and len(factory) >= int(p["offset"]) + len(app)]
    matches = [p for p in candidates if factory[int(p["offset"]) : int(p["offset"]) + len(app)] == app]
    if not matches:
        summary = ", ".join(f"{p['label'] or '?'}:sub=0x{int(p['subtype']):02x}@0x{int(p['offset']):x}+0x{int(p['size']):x}" for p in candidates) or "none"
        raise SystemExit("Factory application payload does not match update image in any app partition; " f"candidates: {summary}")
    return matches[0]


def find_ota(partitions: list[dict[str, int | str]], subtype: int, fallback_label: str) -> dict[str, int | str] | None:
    for p in partitions:
        if p["type"] == 0x00 and p["subtype"] == subtype:
            return p
    for p in partitions:
        if p["type"] == 0x00 and str(p["label"]).lower() == fallback_label:
            return p
    return None


def build_webflasher(app: bytes, factory: bytes, partitions: list[dict[str, int | str]]) -> bytes:
    ota0 = find_ota(partitions, 0x10, "app0")
    ota1 = find_ota(partitions, 0x11, "app1")
    if ota0 is None or ota1 is None:
        summary = ", ".join(f"{p['label'] or '?'}:type=0x{int(p['type']):02x}/sub=0x{int(p['subtype']):02x}@0x{int(p['offset']):x}+0x{int(p['size']):x}" for p in partitions)
        raise SystemExit(f"Compatible OTA0/OTA1 partitions not found: {summary}")

    app0, app1 = int(ota0["offset"]), int(ota1["offset"])
    size0, size1 = int(ota0["size"]), int(ota1["size"])
    if app0 >= app1:
        raise SystemExit(f"Invalid OTA slot order: app0=0x{app0:x}, app1=0x{app1:x}")
    if len(app) > size0 or len(app) > size1:
        raise SystemExit(f"Application image ({len(app)} bytes) exceeds OTA slot sizes 0x{size0:x}/0x{size1:x}")

    flash_start, flash_end = app0, app1 + size1
    for part in partitions:
        if part is ota0 or part is ota1 or int(part["size"]) == 0:
            continue
        part_start = int(part["offset"])
        part_end = part_start + int(part["size"])
        if part_start < flash_end and part_end > flash_start:
            raise SystemExit(f"Web Flasher OTA span 0x{flash_start:x}-0x{flash_end:x} overlaps partition {part['label'] or '?'} at 0x{part_start:x}-0x{part_end:x}")

    required_size = max(len(factory), app0 + size0, app1 + size1)
    image = bytearray(factory)
    if len(image) < required_size:
        image.extend(b"\xff" * (required_size - len(image)))
    image[app0 : app0 + size0] = b"\xff" * size0
    image[app1 : app1 + size1] = b"\xff" * size1
    image[app0 : app0 + len(app)] = app
    image[app1 : app1 + len(app)] = app
    print(f"Built partition-derived dual-slot Web Flasher image: {len(image)} bytes; app0=0x{app0:x}/0x{size0:x}, app1=0x{app1:x}/0x{size1:x}")
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
            if child.is_file() or child.is_symlink(): child.unlink()
            elif child.is_dir():
                import shutil
                shutil.rmtree(child)
    out.mkdir(parents=True, exist_ok=True)
    prefix = f"JARNSEN-MESH-{args.artifact_label}-{args.version}-Build-{args.build}"
    if args.artifact_kind == "uf2":
        uf2s = sorted(build_dir.glob("firmware*.uf2"))
        if not uf2s: raise SystemExit(f"No UF2 firmware found in {build_dir}")
        (out / f"{prefix}-firmware.uf2").write_bytes(uf2s[0].read_bytes())
        variants = ["uf2"]
    else:
        app_path = find_application(build_dir, args.environment)
        factory_path = find_factory(build_dir, args.environment)
        app, factory = app_path.read_bytes(), factory_path.read_bytes()
        if not app or app[0] != 0xE9: raise SystemExit(f"Invalid ESP32 application image: {app_path}")
        partitions = load_partitions(build_dir, factory)
        app_part = find_factory_app_partition(app, factory, partitions)
        app_offset = int(app_part["offset"])
        if factory[app_offset] != 0xE9: raise SystemExit(f"Factory application header invalid at 0x{app_offset:x}: {factory_path}")
        print(f"Validated ESP32 application image: {len(app)} bytes; partition={app_part['label'] or '?'} offset=0x{app_offset:x} size=0x{int(app_part['size']):x}")
        (out / f"{prefix}-update.bin").write_bytes(app)
        (out / f"{prefix}-factory.bin").write_bytes(factory)
        variants = ["update", "factory"]
        if args.webflasher == "true":
            payload = build_webflasher(app, factory, partitions)
            (out / f"{prefix}-webflasher.bin").write_bytes(payload)
            variants.append("webflasher")

    manifest = {"schema": 1, "product": "JARNSEN-MESH", "version": args.version, "board": args.board, "platformio_environment": args.environment, "build": args.build, "source_sha": args.source_sha, "variants": variants}
    (out / f"{prefix}-package-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    readme = f"""JARNSEN-MESH {args.version}\nBoard: {args.board}\nPlatformIO environment: {args.environment}\nBuild: {args.build}\nSource SHA: {args.source_sha}\n\nThis package was compiled from the shared JARNSEN-MESH Unified Core.\nESP32 packages contain update.bin and factory.bin. Boards with a verified\ndual-slot layout additionally contain webflasher.bin. All ESP32 offsets are\nderived from the generated partition table; no board-specific application\noffset is hard-coded. The Wio Tracker L1 keeps its native UF2 image.\n"""
    (out / f"{prefix}-README.txt").write_text(readme, encoding="utf-8")
    checksum_path = out / f"{prefix}-SHA256SUMS.txt"
    checksum_lines = [f"{sha256(path)}  {path.name}" for path in sorted(p for p in out.iterdir() if p.is_file() and p != checksum_path)]
    checksum_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    print(f"Packaged {args.board} -> {out}")
    for path in sorted(out.iterdir()):
        if path.is_file(): print(f"  {path.name}: {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
