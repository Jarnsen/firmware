"""Safe Heltec V3 firmware-only update (8-MB JARNSEN partition layout).

Read installed partition layout and OTA boot selection. Write ONLY the inactive
app partition, verify via esptool, then update the OTHER OTA metadata sector.
The current app, NVS, LoRa settings, and original OTA record stay untouched.
Hardware validation is still required before treating this as production-safe.
"""

from __future__ import annotations

import struct
import tempfile
import time
import zlib
from pathlib import Path
from typing import Any, Callable

TABLE_OFFSET, TABLE_SIZE = 0x8000, 0x1000
OTA_OFFSET, OTA_SIZE, SECTOR_SIZE = 0xE000, 0x2000, 0x1000
APP_TARGETS = ((0x10000, 0x330000), (0x340000, 0x330000))
OTA_VALID, OTA_UNDEFINED = 2, 0xFFFFFFFF


def _crc_candidates(seq: int) -> tuple[int, ...]:
    raw = struct.pack("<I", seq)
    normal = zlib.crc32(raw) & 0xFFFFFFFF
    seeded = zlib.crc32(raw, 0xFFFFFFFF) & 0xFFFFFFFF
    return normal, seeded, seeded ^ 0xFFFFFFFF, normal ^ 0xFFFFFFFF


def _parse_ota(data: bytes) -> tuple[int, int, int, int]:
    """Return active metadata sector, active application, new sequence, CRC mode."""
    if len(data) != OTA_SIZE:
        raise ValueError("OTA-Daten unvollständig.")
    valid = []
    for sector in (0, 1):
        seq, _label, state, crc = struct.unpack_from(
            "<I20sII", data, sector * SECTOR_SIZE
        )
        if seq in (0, OTA_UNDEFINED):
            continue
        modes = [
            n for n, candidate in enumerate(_crc_candidates(seq)) if candidate == crc
        ]
        if not modes:
            continue
        # An interrupted/new OTA transaction must never be silently treated
        # as an older active slot. The bootloader can still select this entry.
        if state in (0, 1):
            raise ValueError(
                "OTA-Bootzustand NEW/PENDING: aktiven Slot nicht sicher bestimmbar."
            )
        if state in (OTA_VALID, OTA_UNDEFINED):
            valid.append((seq, sector, modes[0]))
    if not valid:
        raise ValueError(
            "Keine bestätigten OTA-Bootinformationen gefunden. Update verweigert."
        )
    valid.sort(reverse=True)
    seq, sector, crc_mode = valid[0]
    if seq >= 0xFFFFFFFE:
        raise ValueError("OTA-Sequenzüberlauf. Sicheres Update nicht möglich.")
    active = (seq - 1) % 2
    return sector, active, seq + 1, crc_mode


def _create_ota_sector(seq: int, crc_mode: int) -> bytes:
    sector = bytearray(b"\xff" * SECTOR_SIZE)
    struct.pack_into(
        "<I20sII",
        sector,
        0,
        seq,
        b"\xff" * 20,
        OTA_VALID,
        _crc_candidates(seq)[crc_mode],
    )
    return bytes(sector)


def flash_v3_firmware_only(
    services: Any, port: str, bundle: Any, log: Callable[[str], None] | None
) -> None:
    """Update one inactive app slot; fail closed on unknown partition/OTA state."""
    from flash_runtime import _stream_esptool
    from unified_service_v2 import _parse_partition_table

    if not getattr(bundle, "factory", None) or not getattr(bundle, "update", None):
        raise ValueError("V3-Firmwarepaket ohne Factory-Image oder Update-Image. Kein Flashen.")
    firmware_path, factory_path = Path(bundle.update), Path(bundle.factory)
    firmware, factory = firmware_path.read_bytes(), factory_path.read_bytes()
    if (
        len(firmware) < 256 * 1024
        or len(firmware) > APP_TARGETS[0][1]
        or firmware[0] != 0xE9
    ):
        raise ValueError("V3-Update-Image ist ungültig oder zu groß.")
    if len(factory) < TABLE_OFFSET + TABLE_SIZE:
        raise ValueError("Factory-Image enthält keine Partitionstabelle.")
    baud = str(getattr(services, "_jarnsen_flash_baud", "460800"))
    if baud not in ("115200", "230400", "460800", "921600"):
        baud = "460800"
    common = [
        "--chip",
        "esp32s3",
        "--before",
        "default-reset",
        "--after",
        "hard-reset",
        "--baud",
        baud,
    ]

    def command(
        args: list[str], stage: str, low: float, high: float, timeout: int = 120
    ) -> None:
        _stream_esptool(
            services,
            port,
            [*common, *args],
            timeout=timeout,
            stage=stage,
            phase_start=low,
            phase_end=high,
            log=log,
        )

    with tempfile.TemporaryDirectory(prefix="jarnsen-v3-ota-") as temp:
        directory = Path(temp)
        real_table, real_ota = directory / "partition.bin", directory / "otadata.bin"
        command(
            ["read-flash", hex(TABLE_OFFSET), hex(TABLE_SIZE), str(real_table)],
            "Installierte Partitionen lesen",
            0.02,
            0.07,
        )
        if real_table.read_bytes() != factory[TABLE_OFFSET : TABLE_OFFSET + TABLE_SIZE]:
            raise ValueError(
                "V3-Partitionstabelle auf dem Gerät weicht vom Paket ab. Keine Änderung."
            )
        parts = _parse_partition_table(factory)
        apps = sorted(
            (int(p["offset"]), int(p["size"]))
            for p in parts
            if int(p["type"]) == 0 and int(p["subtype"]) in (0x10, 0x11)
        )
        if tuple(apps) != APP_TARGETS:
            raise ValueError("Unbekanntes OTA-App-Layout. Update verweigert.")
        ota = [p for p in parts if int(p["type"]) == 1 and int(p["subtype"]) == 0]
        if (
            len(ota) != 1
            or int(ota[0]["offset"]) != OTA_OFFSET
            or int(ota[0]["size"]) != OTA_SIZE
        ):
            raise ValueError("Unbekannte OTA-Metadatenpartition.")
        command(
            ["read-flash", hex(OTA_OFFSET), hex(OTA_SIZE), str(real_ota)],
            "OTA-Startdaten lesen",
            0.07,
            0.13,
        )
        old = real_ota.read_bytes()
        active_sector, active_slot, next_seq, crc_mode = _parse_ota(old)
        target_app = 1 - active_slot
        target_offset, capacity = APP_TARGETS[target_app]
        if len(firmware) > capacity:
            raise ValueError("App passt nicht in den inaktiven OTA-Slot.")
        next_sector = 1 - active_sector
        metadata_offset = OTA_OFFSET + next_sector * SECTOR_SIZE
        backup_dir = Path.home() / ".jarnsen-mesh" / "v3-ota-recovery"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"otadata-{int(time.time())}-active{active_slot}.bin"
        backup_path.write_bytes(old)
        if backup_path.stat().st_size != OTA_SIZE:
            raise IOError(
                "OTA-Bootinformationen konnten nicht vollständig gesichert werden."
            )
        selected = directory / "otadata-next.bin"
        selected.write_bytes(_create_ota_sector(next_seq, crc_mode))
        if log:
            log(
                f"V3-OTA SICHERUNG · {backup_path} · bisher OTA{active_slot}, neu OTA{target_app}"
            )
        command(
            [
                "write-flash",
                "--flash-mode",
                "dio",
                "--flash-freq",
                "80m",
                "--flash-size",
                "keep",
                hex(target_offset),
                str(firmware_path),
            ],
            "Firmware in inaktiven V3-App-Slot schreiben",
            0.15,
            0.80,
            timeout=600,
        )
        # Metadata written LAST. The former app and its selected OTA record
        # remain available even if this final write or the new boot fails.
        # Register rollback BEFORE changing the selector: an interrupted
        # selector write can be recovered by replacing only this sector.
        setattr(
            services,
            "_jarnsen_v3_pending_boot_rollback",
            (str(port), int(metadata_offset), str(backup_path)),
        )
        command(
            [
                "write-flash",
                "--flash-mode",
                "dio",
                "--flash-freq",
                "80m",
                "--flash-size",
                "keep",
                hex(metadata_offset),
                str(selected),
            ],
            "V3 OTA-Startslot umschalten",
            0.81,
            0.91,
        )
        if log:
            log(
                f"V3-OTA FERTIG · OTA{active_slot} unangetastet, OTA{target_app} aktiv · "
                f"Recovery-Metadaten: {backup_path}"
            )


def rollback_v3_boot_selector(services: Any, log: Callable[[str], None] | None) -> bool:
    """Re-select the previously bootable app after a failed post-flash health check."""
    pending = getattr(services, "_jarnsen_v3_pending_boot_rollback", None)
    if not pending:
        return False
    from flash_runtime import _stream_esptool

    port, metadata_offset, backup_path = pending
    original = Path(backup_path).read_bytes()
    if len(original) != OTA_SIZE or metadata_offset not in (
        OTA_OFFSET,
        OTA_OFFSET + SECTOR_SIZE,
    ):
        raise ValueError("V3 OTA-Recovery-Daten sind unvollständig oder ungültig.")
    sector_index = (metadata_offset - OTA_OFFSET) // SECTOR_SIZE
    old_sector = original[sector_index * SECTOR_SIZE : (sector_index + 1) * SECTOR_SIZE]
    with tempfile.TemporaryDirectory(prefix="jarnsen-v3-rollback-") as directory:
        image = Path(directory) / "old-selector.bin"
        image.write_bytes(old_sector)
        baud = str(getattr(services, "_jarnsen_flash_baud", "460800"))
        if baud not in ("115200", "230400", "460800", "921600"):
            baud = "460800"
        _stream_esptool(
            services,
            port,
            [
                "--chip",
                "esp32s3",
                "--before",
                "default-reset",
                "--after",
                "hard-reset",
                "--baud",
                baud,
                "write-flash",
                "--flash-mode",
                "dio",
                "--flash-freq",
                "80m",
                "--flash-size",
                "keep",
                hex(metadata_offset),
                str(image),
            ],
            timeout=120,
            stage="V3 alten OTA-Bootslot wiederherstellen",
            phase_start=0.91,
            phase_end=0.98,
            log=log,
        )
    setattr(services, "_jarnsen_v3_pending_boot_rollback", None)
    if log:
        log(f"V3-OTA ROLLBACK · alter Bootslot wieder aktiv · Sicherung: {backup_path}")
    return True
