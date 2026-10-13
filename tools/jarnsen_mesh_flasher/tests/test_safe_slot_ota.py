"""Regression tests: safe inactive-slot updates for all other ESP32 boards."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from safe_slot_ota import CHIPS, flash_firmware_only, inspect_layout
from v3_safe_ota import _create_ota_sector


def parts(app_size, second_offset, *, first_size=None, ota_offset=0xE000):
    return [
        {
            "type": 0,
            "subtype": 0x10,
            "offset": 0x10000,
            "size": app_size if first_size is None else first_size,
        },
        {"type": 0, "subtype": 0x11, "offset": second_offset, "size": app_size},
        {"type": 1, "subtype": 0x00, "offset": ota_offset, "size": 0x2000},
    ]


@pytest.mark.parametrize(
    ("board_key", "max_app", "second"),
    [
        ("tracker", 0x330000, 0x340000),
        ("heltec_v4", 0x640000, 0x650000),
        ("tbeam_supreme", 0x330000, 0x340000),
        ("tbeam", 0x330000, 0x340000),
    ],
)
def test_layout_dynamic_addresses(board_key, max_app, second):
    assert board_key in CHIPS
    apps, ota = inspect_layout(parts(max_app, second), 512 * 1024)
    assert apps == [(0x10000, max_app), (second, max_app)]
    assert ota == 0xE000


def test_tbeam_old_4mb_ota_1_too_small_fails_before_writing():
    legacy = parts(0x0A0000, 0x260000, first_size=0x250000)
    with pytest.raises(ValueError, match="zu klein"):
        inspect_layout(legacy, 1024 * 1024)


@pytest.mark.parametrize(
    "bad",
    [
        [],
        [{"type": 0, "subtype": 0x10, "offset": 0x10000, "size": 0x330000}],
        parts(0x330000, 0x12000),
        parts(0x330000, 0x340000, ota_offset=0x10000),
    ],
)
def test_unknown_or_overlapping_layout_refused(bad):
    with pytest.raises(ValueError):
        inspect_layout(bad, 512 * 1024)


def simulate(
    monkeypatch,
    tmp_path,
    *,
    board_key="tracker",
    installed_table_matches=True,
    bad_readback=False,
    seq=1,
    erased_ota=False,
):
    """Offline fake esptool to verify precise read/write addresses."""
    import safe_slot_ota as updater

    size = 512 * 1024
    update = tmp_path / "firmware.bin"
    payload = b"\xe9" + b"\x88" * (size - 1)
    update.write_bytes(payload)
    factory = tmp_path / "factory.bin"
    factory_data = bytearray(b"\xff" * (updater.TABLE_OFFSET + updater.TABLE_SIZE))
    factory_data[updater.TABLE_OFFSET : updater.TABLE_OFFSET + 4] = b"\xaa\x50\x00\x10"
    factory.write_bytes(factory_data)
    installed_table = bytes(factory_data[updater.TABLE_OFFSET :])
    if not installed_table_matches:
        installed_table = b"\x00" * updater.TABLE_SIZE
    metadata = bytearray(b"\xff" * updater.OTA_SIZE)
    if not erased_ota:
        metadata[0 : updater.SECTOR] = _create_ota_sector(seq, 0)
    write_addresses = []
    read_addresses = []
    verified = []
    flash = {}
    fake_runtime = types.ModuleType("flash_runtime")

    def esptool(_services, _port, command, **_kwargs):
        if "read-flash" in command:
            index = command.index("read-flash")
            addr = int(command[index + 1], 16)
            length = int(command[index + 2], 16)
            read_addresses.append(addr)
            if addr == updater.TABLE_OFFSET:
                data = installed_table
            elif addr == 0xE000:
                data = bytes(metadata)
            elif addr == 0x10000 and length == 0x1000:
                data = b"\xe9" + b"\x00" * (length - 1)
            else:
                data = flash.get(addr, b"\xff" * length)
                if bad_readback:
                    data = b"\x00" * len(data)
            Path(command[index + 3]).write_bytes(data)
        elif "write-flash" in command:
            idx = command.index("write-flash")
            addr = int(command[-2], 16)
            data = Path(command[-1]).read_bytes()
            write_addresses.append(addr)
            flash[addr] = data
        else:
            raise AssertionError("unexpected esptool command: " + repr(command))

    fake_runtime._stream_esptool = esptool
    monkeypatch.setitem(sys.modules, "flash_runtime", fake_runtime)
    fake_unified = types.ModuleType("unified_service_v2")
    app_part_size = 0x640000 if board_key == "heltec_v4" else 0x330000
    app2_offset = 0x650000 if board_key == "heltec_v4" else 0x340000
    fake_unified._parse_partition_table = lambda _factory: parts(
        app_part_size, app2_offset
    )
    fake_unified.prepare_supreme_download_mode = lambda _services, port, _log: port
    monkeypatch.setitem(sys.modules, "unified_service_v2", fake_unified)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    services = types.SimpleNamespace(
        _jarnsen_flash_baud="115200",
        verify_node=lambda _port, expected_board: verified.append(expected_board),
    )
    bundle = types.SimpleNamespace(factory=factory, update=update, board_key=board_key)
    return services, bundle, write_addresses, read_addresses, verified, flash


@pytest.mark.parametrize(
    ("board", "seq", "target", "sector"),
    [
        ("tracker", 1, 0x340000, 0xF000),
        ("tracker", 2, 0x10000, 0xF000),
        ("heltec_v4", 1, 0x650000, 0xF000),
        ("tbeam_supreme", 1, 0x340000, 0xF000),
        ("tbeam", 1, 0x340000, 0xF000),
    ],
)
def test_single_slot_and_boot_selector_written_last(
    monkeypatch, tmp_path, board, seq, target, sector
):
    services, bundle, writes, reads, verified, memory = simulate(
        monkeypatch,
        tmp_path,
        board_key=board,
        seq=seq,
    )
    flash_firmware_only(services, "COM13", board, bundle)
    assert writes == [target, sector]
    assert verified == [board]
    assert updater_digest(memory[target]) == updater_digest(bundle.update.read_bytes())
    assert 0x9000 not in writes
    assert (0x10000 if target == 0x340000 else 0x340000) not in writes
    assert services._jarnsen_safe_ota_pending_boot_rollback["board_key"] == board


def updater_digest(blob):
    import hashlib

    return hashlib.sha256(blob).digest()


def test_rollback_restores_old_metadata_without_overwriting_active_app(
    monkeypatch, tmp_path
):
    import safe_slot_ota as ota

    services, bundle, writes, _reads, _verified, flash = simulate(
        monkeypatch, tmp_path, board_key="tracker", seq=1
    )
    flash_firmware_only(services, "COM13", "tracker", bundle)
    record = services._jarnsen_safe_ota_pending_boot_rollback
    original = Path(record["backup"]).read_bytes()
    assert ota.rollback_boot_selector(services)
    assert writes == [0x340000, 0xF000, 0xF000]
    assert flash[0xF000] == original[0x1000:0x2000]
    assert services._jarnsen_safe_ota_pending_boot_rollback is None


def test_mismatched_installed_table_fails_without_any_write(monkeypatch, tmp_path):
    services, bundle, writes, _reads, _verified, _flash = simulate(
        monkeypatch,
        tmp_path,
        installed_table_matches=False,
    )
    with pytest.raises(ValueError, match="Partitionslayout"):
        flash_firmware_only(services, "COM13", "tracker", bundle)
    assert writes == []


def test_image_readback_mismatch_keeps_old_boot_selector(monkeypatch, tmp_path):
    services, bundle, writes, _reads, _verified, _flash = simulate(
        monkeypatch,
        tmp_path,
        bad_readback=True,
    )
    with pytest.raises(IOError, match="Rückleseprüfung"):
        flash_firmware_only(services, "COM13", "tracker", bundle)
    assert writes == [0x340000]
    assert getattr(services, "_jarnsen_safe_ota_pending_boot_rollback", None) is None


def test_erased_ota_metadata_requires_valid_running_image(monkeypatch, tmp_path):
    services, bundle, writes, reads, verified, _flash = simulate(
        monkeypatch,
        tmp_path,
        erased_ota=True,
    )
    flash_firmware_only(services, "COM13", "tracker", bundle)
    assert 0x10000 in reads
    assert verified == ["tracker"]
    assert writes == [0x340000, 0xF000]


def test_bad_bundle_identity_cannot_write(monkeypatch, tmp_path):
    services, bundle, writes, _reads, _verified, _flash = simulate(
        monkeypatch,
        tmp_path,
    )
    bundle.board_key = "tbeam"
    with pytest.raises(ValueError, match="Board"):
        flash_firmware_only(services, "COM13", "tracker", bundle)
    assert writes == []
