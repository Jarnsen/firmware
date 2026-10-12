from __future__ import annotations

import importlib
import struct
import sys
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
APP_DIR = HERE.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def _initial_otadata(ota, seq=1, sector=0):
    result = bytearray(b"\xff" * ota.OTA_SIZE)
    struct.pack_into(
        "<I20sII",
        result,
        sector * ota.SECTOR_SIZE,
        seq,
        b"\xff" * 20,
        ota.OTA_VALID,
        ota._crc_candidates(seq)[0],
    )
    return bytes(result)


def test_v3_slot_rotation_preserves_previous_slot():
    import v3_safe_ota as ota

    before = _initial_otadata(ota)
    sector, active, next_seq, mode = ota._parse_ota(before)
    assert (sector, active, next_seq, mode) == (0, 0, 2, 0)
    updated = before[:4096] + ota._create_ota_sector(next_seq, mode)
    assert updated[:4096] == before[:4096]
    assert ota._parse_ota(updated)[:3] == (1, 1, 3)


def test_v3_pending_ota_state_must_not_select_older_slot():
    import v3_safe_ota as ota

    old = bytearray(_initial_otadata(ota))
    newer = bytearray(ota._create_ota_sector(2, 0))
    struct.pack_into("<I", newer, 24, 1)  # ESP_OTA_IMG_PENDING_VERIFY
    old[ota.SECTOR_SIZE :] = newer
    with pytest.raises(ValueError, match="NEW/PENDING"):
        ota._parse_ota(bytes(old))


def test_v3_corrupt_otadata_fails_closed():
    import v3_safe_ota as ota

    with pytest.raises(ValueError, match="Bootinformationen"):
        ota._parse_ota(b"\xff" * ota.OTA_SIZE)
    with pytest.raises(ValueError, match="unvollständig"):
        ota._parse_ota(b"\xff" * 32)
    damaged = bytearray(_initial_otadata(ota))
    struct.pack_into("<I", damaged, 28, 0)
    with pytest.raises(ValueError, match="Bootinformationen"):
        ota._parse_ota(bytes(damaged))


def test_v3_unknown_partition_table_never_writes(monkeypatch, tmp_path):
    import v3_safe_ota as ota

    firmware = tmp_path / "update.bin"
    firmware.write_bytes(b"\xe9" + b"\x00" * (256 * 1024))
    factory = tmp_path / "factory.bin"
    factory.write_bytes(b"\xff" * (ota.TABLE_OFFSET + ota.TABLE_SIZE))

    fake_runtime = types.ModuleType("flash_runtime")
    writes = []

    def stream(_services, _port, args, **_kwargs):
        command = "read-flash" if "read-flash" in args else "write-flash"
        if command == "write-flash":
            writes.append(args)
        else:
            Path(args[-1]).write_bytes(b"\x00" * ota.TABLE_SIZE)

    fake_runtime._stream_esptool = stream
    monkeypatch.setitem(sys.modules, "flash_runtime", fake_runtime)
    fake_core = types.ModuleType("unified_service_v2")
    fake_core._parse_partition_table = lambda _factory: []
    monkeypatch.setitem(sys.modules, "unified_service_v2", fake_core)
    ota = importlib.reload(ota)
    services = types.SimpleNamespace(_jarnsen_flash_baud="115200")
    bundle = types.SimpleNamespace(update=firmware, factory=factory)

    with pytest.raises(ValueError, match="Partitionstabelle"):
        ota.flash_v3_firmware_only(services, "COM13", bundle, None)
    assert writes == []


def test_v3_writes_only_inactive_app_and_ota_metadata(monkeypatch, tmp_path):
    import v3_safe_ota as ota

    firmware = tmp_path / "update.bin"
    firmware.write_bytes(b"\xe9" + b"\x00" * (256 * 1024))
    factory = tmp_path / "factory.bin"
    factory.write_bytes(b"\xff" * (ota.TABLE_OFFSET + ota.TABLE_SIZE))
    initial = _initial_otadata(ota)
    writes = []
    fake_runtime = types.ModuleType("flash_runtime")

    def stream(_services, _port, args, **_kwargs):
        if "read-flash" in args:
            start = args.index("read-flash")
            offset = int(args[start + 1], 16)
            Path(args[-1]).write_bytes(
                initial if offset == ota.OTA_OFFSET else b"\xff" * ota.TABLE_SIZE
            )
        else:
            start = args.index("write-flash")
            offset = int(args[-2], 16)
            writes.append((offset, Path(args[-1]).read_bytes()))

    fake_runtime._stream_esptool = stream
    monkeypatch.setitem(sys.modules, "flash_runtime", fake_runtime)
    fake_core = types.ModuleType("unified_service_v2")
    fake_core._parse_partition_table = lambda _factory: [
        {"type": 0, "subtype": 0x10, "offset": 0x10000, "size": 0x330000},
        {"type": 0, "subtype": 0x11, "offset": 0x340000, "size": 0x330000},
        {"type": 1, "subtype": 0, "offset": 0xE000, "size": 0x2000},
    ]
    monkeypatch.setitem(sys.modules, "unified_service_v2", fake_core)
    monkeypatch.setattr(ota.Path, "home", classmethod(lambda cls: tmp_path))
    ota = importlib.reload(ota)
    services = types.SimpleNamespace(_jarnsen_flash_baud="115200")
    bundle = types.SimpleNamespace(update=firmware, factory=factory)
    ota.flash_v3_firmware_only(services, "COM13", bundle, None)

    assert [offset for offset, _data in writes] == [0x340000, 0xF000]
    assert writes[0][1] == firmware.read_bytes()
    selected = _initial_otadata(ota)[:4096] + writes[1][1]
    assert ota._parse_ota(selected)[1] == 1
    assert services._jarnsen_v3_pending_boot_rollback[1] == 0xF000
