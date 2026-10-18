"""Firmware-only inactive-slot updates for verified JARNSEN ESP32 boards.

Never infer app addresses from a board name: compare the REAL 0x8000 partition
table to the signed/validated firmware bundle, then inspect OTA metadata.
The original app and its metadata record are left intact for rollback.

V3 retains its hardware-tested dedicated path. Wio uses UF2.
"""

from __future__ import annotations

import hashlib
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from v3_safe_ota import _create_ota_sector, _parse_ota

# Explicit supported hardware.  Do not automatically include new boards.
CHIPS = {
    "tracker": "esp32s3",
    "heltec_v4": "esp32s3",
    "tbeam": "esp32",
    "tbeam_supreme": "esp32s3",
}
TABLE_OFFSET = 0x8000
TABLE_SIZE = 0x1000
SECTOR = 0x1000
OTA_SIZE = 0x2000


def inspect_layout(
    parts: list[dict], firmware_length: int
) -> tuple[list[tuple[int, int]], int]:
    """Fail closed unless there are exactly two non-overlapping OTA app slots.

    The active image must fit in the other slot for a reversible update.
    """
    apps = [
        (int(p["offset"]), int(p["size"]), int(p["subtype"]))
        for p in parts
        if int(p["type"]) == 0 and int(p["subtype"]) in (0x10, 0x11)
    ]
    if len(apps) != 2 or {part[2] for part in apps} != {0x10, 0x11}:
        raise ValueError(
            "Genau OTA0 und OTA1 sind für ein sicheres Update erforderlich."
        )
    apps.sort(key=lambda p: p[2])
    for offset, size, _subtype in apps:
        if offset % SECTOR or size % SECTOR or size < firmware_length:
            raise ValueError(
                f"OTA-Slot 0x{offset:x}: zu klein oder nicht sektorbündig. "
                "Firmware-only-Update verweigert; kein Erstflash ausgeführt."
            )
    if max(apps[0][0], apps[1][0]) < min(
        apps[0][0] + apps[0][1], apps[1][0] + apps[1][1]
    ):
        raise ValueError("OTA-App-Partitionen überlappen sich.")
    ota = [
        (int(p["offset"]), int(p["size"]))
        for p in parts
        if int(p["type"]) == 1 and int(p["subtype"]) == 0
    ]
    if len(ota) != 1 or ota[0][1] != OTA_SIZE or ota[0][0] % SECTOR:
        raise ValueError("Unbekannte oder fehlende OTA-Metadatenpartition.")
    otadata_offset = ota[0][0]
    for offset, size, _subtype in apps:
        if offset < otadata_offset + OTA_SIZE and otadata_offset < offset + size:
            raise ValueError("OTA-Metadaten überschneiden eine App-Partition.")
    return [(offset, size) for offset, size, _ in apps], otadata_offset


def _baud(services: Any) -> str:
    value = str(getattr(services, "_jarnsen_flash_baud", "460800"))
    return value if value in {"115200", "230400", "460800", "921600"} else "460800"


def _transport(board_key: str, *, final: bool = False) -> list[str]:
    # Native USB Serial/JTAG: after explicit preparation it must
    # not be put into bootloader again between read/write/verification stages.
    if board_key in {"tracker", "tbeam_supreme"}:
        return [
            "--chip",
            "esp32s3",
            "--before",
            "no-reset",
            "--after",
            "watchdog-reset" if final else "no-reset",
            "--baud",
            "460800",
        ]
    return [
        "--chip",
        CHIPS[board_key],
        "--before",
        "default-reset",
        "--after",
        "hard-reset" if final else "no-reset",
        "--baud",
        "460800",
    ]


def _run(
    services: Any,
    port: str,
    args: list[str],
    log: Callable[[str], None] | None,
    label: str,
    start: float,
    end: float,
    timeout: int = 180,
    *,
    check: bool = True,
):
    from flash_runtime import _stream_esptool

    return _stream_esptool(
        services,
        port,
        args,
        timeout=timeout,
        stage=label,
        phase_start=start,
        phase_end=end,
        log=log,
        check=check,
    )


def _verified_write_reset_disconnect(result: Any) -> bool:
    """True only when bytes were verified before USB vanished during reset."""
    if result is None or int(getattr(result, "returncode", 0) or 0) == 0:
        return False
    output = str(getattr(result, "stdout", "") or "")
    lowered = output.casefold()
    verified = "hash of data verified" in lowered
    reset_started = (
        "hard resetting with a watchdog" in lowered
        or "hard resetting via rts pin" in lowered
        or "hard resetting" in lowered
    )
    transport_lost = (
        "serial exception error occurred" in lowered
        or "cannot configure port" in lowered
        or "device was specified" in lowered
        or "device does not exist" in lowered
    )
    return verified and reset_started and transport_lost


def _accept_verified_reset_disconnect(
    services: Any,
    result: Any,
    *,
    label: str,
    log: Callable[[str], None] | None,
) -> None:
    if result is None or int(getattr(result, "returncode", 0) or 0) == 0:
        return
    if _verified_write_reset_disconnect(result):
        if log:
            log(
                f"{label} · Flash-Hash verifiziert · USB-Port verschwand erst beim "
                "Reset · wird als erwartete USB-Neuanmeldung behandelt"
            )
        return
    output = str(getattr(result, "stdout", "") or "").strip()
    raise services.FlasherError(
        output or f"{label} fehlgeschlagen (Exit {getattr(result, 'returncode', '?')})"
    )


def flash_firmware_only(
    services: Any,
    port: str,
    board_key: str,
    bundle: Any,
    log: Callable[[str], None] | None = None,
) -> None:
    if board_key not in CHIPS:
        raise ValueError("Kein abgesichertes Single-Slot-Verfahren für dieses Board.")
    if not getattr(bundle, "factory", None) or not getattr(bundle, "update", None):
        raise ValueError(
            "Factory-/Update-Image fehlen. Ohne gültiges Layout kein Flash."
        )
    if str(getattr(bundle, "board_key", "")).strip() != board_key:
        raise ValueError(
            "Firmwarepaket und angeschlossenes Board stimmen nicht überein."
        )

    update = Path(bundle.update)
    factory = Path(bundle.factory).read_bytes()
    firmware = update.read_bytes()
    if len(factory) < TABLE_OFFSET + TABLE_SIZE:
        raise ValueError("Firmwarepaket enthält keine vollständige Partitionstabelle.")
    if len(firmware) < 256 * 1024 or firmware[0] != 0xE9:
        raise ValueError("Firmware-Image fehlt oder besitzt keinen ESP32-App-Header.")

    from unified_service_v2 import _parse_partition_table

    parts = _parse_partition_table(factory)
    apps, ota_offset = inspect_layout(parts, len(firmware))
    if str(getattr(bundle, "board_key", "")) != board_key:
        raise ValueError("Falsche Boardkennung im Firmware-Bundle.")

    # Authenticate physical running board BEFORE putting it in ROM bootloader.
    # A COM-port/USB VID alone is NOT sufficient hardware identity.
    checker = getattr(services, "verify_node", None)
    if not callable(checker):
        raise ValueError("Live-Hardwareprüfung fehlt. Sicheres Update verweigert.")
    checker(port, expected_board=board_key)

    flash_port = port
    if board_key == "tracker":
        prepare = getattr(services, "prepare_s3_download_mode", None)
        if not callable(prepare):
            raise ValueError("Sicherer Tracker-Bootloaderdienst fehlt. Kein Flash.")
        flash_port = prepare(port, board_key, log=log)
    elif board_key == "tbeam_supreme":
        from unified_service_v2 import prepare_supreme_download_mode

        flash_port = prepare_supreme_download_mode(services, port, log)

    common = _transport(board_key)
    # Consistent baud during one transaction, even on slow T-Beam bridge.
    baud = _baud(services)
    common[common.index("--baud") + 1] = baud

    def command(
        args: list[str],
        label: str,
        lo: float,
        hi: float,
        *,
        final: bool = False,
        timeout: int = 180,
        check: bool = True,
    ):
        base = list(common)
        if final:
            base[base.index("--after") + 1] = (
                "watchdog-reset"
                if board_key in {"tracker", "tbeam_supreme"}
                else "hard-reset"
            )
        return _run(
            services,
            flash_port,
            [*base, *args],
            log,
            label,
            lo,
            hi,
            timeout,
            check=check,
        )

    with tempfile.TemporaryDirectory(prefix="jarnsen-safe-ota-") as temp:
        work = Path(temp)
        installed_table = work / "partitions.bin"
        installed_ota = work / "otadata.bin"

        # Read-only checks always precede the first write/erase instruction.
        command(
            ["read-flash", hex(TABLE_OFFSET), hex(TABLE_SIZE), str(installed_table)],
            "Installierte Partitionen prüfen",
            0.02,
            0.08,
        )
        if (
            installed_table.read_bytes()
            != factory[TABLE_OFFSET : TABLE_OFFSET + TABLE_SIZE]
        ):
            raise ValueError(
                "Installiertes Partitionslayout ist nicht identisch zum Paket. "
                "Keine Änderung am Flash."
            )

        command(
            ["read-flash", hex(ota_offset), hex(OTA_SIZE), str(installed_ota)],
            "Aktive OTA-Bootauswahl auslesen",
            0.09,
            0.15,
        )
        old_ota = installed_ota.read_bytes()
        sector, active, next_seq, crc_mode = _parse_ota(old_ota)
        if active not in (0, 1):
            raise ValueError("Aktiver OTA-App-Slot nicht zuverlässig bestimmbar.")

        if old_ota == b"\xff" * OTA_SIZE:
            # With no factory partition, an erased OTA selector boots OTA0.
            # Check the actual app image header, not just the assumed layout.
            header = work / "current-ota0.bin"
            command(
                ["read-flash", hex(apps[0][0]), "0x1000", str(header)],
                "Erstmigration: aktiven OTA0-Header prüfen",
                0.15,
                0.18,
            )
            actual_header = header.read_bytes()
            if len(actual_header) != SECTOR or actual_header[0] != 0xE9:
                raise ValueError("Leere OTA-Daten, OTA0-App-Header ungültig.")

        target_slot = 1 - active
        target_offset, target_size = apps[target_slot]
        if len(firmware) > target_size:
            raise ValueError(
                "Inaktiver OTA-Slot ist zu klein; bestehende Firmware bleibt unverändert."
            )

        backup_dir = Path.home() / ".jarnsen-mesh" / "ota-recovery" / board_key
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"otadata-{int(time.time())}-{active}.bin"
        backup_path.write_bytes(old_ota)
        if backup_path.read_bytes() != old_ota:
            raise IOError("OTA-Metadatenbackup fehlgeschlagen.")
        replacement_sector = 1 - sector
        selector_offset = ota_offset + replacement_sector * SECTOR
        next_selector = work / "next-selector.bin"
        next_selector.write_bytes(_create_ota_sector(next_seq, crc_mode))

        if log:
            log(
                f"SINGLE-SLOT PLAN · Board={board_key} · OTA{active} behalten "
                f"· OTA{target_slot}@0x{target_offset:x} beschreiben "
                f"· Backup={backup_path}"
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
                str(update),
            ],
            "Nur inaktiven App-Slot schreiben",
            0.19,
            0.78,
            timeout=700,
        )

        # Validate the bytes ON CHIP before changing the boot selector.
        verify_copy = work / "readback.bin"
        command(
            ["read-flash", hex(target_offset), hex(len(firmware)), str(verify_copy)],
            "Geschriebenes Image vollständig zurücklesen",
            0.79,
            0.91,
            timeout=700,
        )
        if (
            hashlib.sha256(verify_copy.read_bytes()).digest()
            != hashlib.sha256(firmware).digest()
        ):
            raise IOError(
                "Flash-Rückleseprüfung fehlgeschlagen. Alter Bootslot bleibt aktiv."
            )

        # Register recoverable selector BEFORE the only metadata write.
        services._jarnsen_safe_ota_pending_boot_rollback = {
            "port": str(port),
            "board_key": board_key,
            "metadata_offset": int(selector_offset),
            "backup": str(backup_path),
            "sector_index": int(replacement_sector),
        }
        selector_result = command(
            [
                "write-flash",
                "--flash-mode",
                "dio",
                "--flash-freq",
                "80m",
                "--flash-size",
                "keep",
                hex(selector_offset),
                str(next_selector),
            ],
            "OTA-Bootauswahl zuletzt umschalten",
            0.92,
            0.97,
            final=True,
            check=False,
        )
        _accept_verified_reset_disconnect(
            services,
            selector_result,
            label="OTA-Bootauswahl zuletzt umschalten",
            log=log,
        )
        if log:
            log(
                f"SINGLE-SLOT ERFOLG · OTA{target_slot} ausgewaehlt · "
                f"OTA{active} + NVS unveraendert · Boot-Prüfung folgt"
            )


def rollback_boot_selector(
    services: Any,
    log: Callable[[str], None] | None = None,
) -> bool:
    state = getattr(services, "_jarnsen_safe_ota_pending_boot_rollback", None)
    if not state:
        return False
    board_key = str(state["board_key"])
    if board_key not in CHIPS:
        raise ValueError("Rollback-Board nicht unterstützt.")
    image = Path(state["backup"]).read_bytes()
    if len(image) != OTA_SIZE or state["sector_index"] not in (0, 1):
        raise ValueError("Rollback-Sicherung unvollständig.")
    sector = int(state["sector_index"])
    metadata_offset = int(state["metadata_offset"])
    if metadata_offset % SECTOR or sector not in (0, 1):
        raise ValueError("Rollback-Ziel ungültig.")
    old_selector = image[sector * SECTOR : (sector + 1) * SECTOR]
    flash_port = str(state["port"])
    if board_key == "tracker":
        prepare = getattr(services, "prepare_s3_download_mode", None)
        if not callable(prepare):
            raise ValueError("Sicherer Tracker-Bootloaderdienst fehlt. Kein Rollback.")
        flash_port = prepare(flash_port, board_key, log=log)
    elif board_key == "tbeam_supreme":
        from unified_service_v2 import prepare_supreme_download_mode

        flash_port = prepare_supreme_download_mode(services, flash_port, log)
    with tempfile.TemporaryDirectory(prefix="jarnsen-safe-rollback-") as temp:
        rollback_img = Path(temp) / "selector.bin"
        rollback_img.write_bytes(old_selector)
        base = _transport(board_key, final=True)
        base[base.index("--baud") + 1] = _baud(services)
        rollback_result = _run(
            services,
            flash_port,
            [
                *base,
                "write-flash",
                "--flash-mode",
                "dio",
                "--flash-freq",
                "80m",
                "--flash-size",
                "keep",
                hex(metadata_offset),
                str(rollback_img),
            ],
            log,
            "Letzten funktionsfähigen OTA-Bootslot wiederherstellen",
            0.97,
            0.99,
            check=False,
        )
        _accept_verified_reset_disconnect(
            services,
            rollback_result,
            label="Letzten funktionsfähigen OTA-Bootslot wiederherstellen",
            log=log,
        )
    services._jarnsen_safe_ota_pending_boot_rollback = None
    if log:
        log(
            f"SINGLE-SLOT ROLLBACK · vorherige Bootauswahl wiederhergestellt · {state['backup']}"
        )
    return True
