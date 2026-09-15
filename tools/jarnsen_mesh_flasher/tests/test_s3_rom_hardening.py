from __future__ import annotations

import importlib
import subprocess
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
APP_DIR = HERE.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


@dataclass
class Fingerprint:
    port: str
    serial_number: str
    location: str = ""
    vid: int | None = 0x303A
    pid: int | None = 0x1001
    hwid: str = ""
    description: str = ""


class Sessions:
    def __init__(self, fingerprints: dict[str, Fingerprint]):
        self.fingerprints = {key.upper(): value for key, value in fingerprints.items()}

    def remember(self, port: str):
        return self.fingerprints.get(str(port).upper())

    def _read_fingerprint(self, port: str):
        return self.fingerprints.get(str(port).upper())


def _completed(
    args: list[str] | None = None, returncode: int = 0, text: str = "ROM OK"
):
    return subprocess.CompletedProcess(args or ["esptool"], returncode, text, "")


def _reload_hardening(monkeypatch, stream, raw_command=None):
    fake_runtime = types.ModuleType("flash_runtime")
    fake_runtime._stream_esptool = stream
    monkeypatch.setitem(sys.modules, "flash_runtime", fake_runtime)

    fake_radio = types.ModuleType("radio_profile_node_sync")
    if raw_command is None:
        def raw_command(*_a, **_kw):
            raise AssertionError("Firmware command must not be used on this path")
    fake_radio._raw_command = raw_command
    monkeypatch.setitem(sys.modules, "radio_profile_node_sync", fake_radio)

    import s3_rom_hardening

    hardening = importlib.reload(s3_rom_hardening)
    monkeypatch.setattr(hardening.time, "sleep", lambda *_a, **_kw: None)
    return hardening, fake_runtime


def _services(sessions: Sessions, waiter):
    return types.SimpleNamespace(
        FlasherError=RuntimeError,
        device_sessions=sessions,
        wait_for_device_reconnect=waiter,
    )


def test_tracker_manual_rom_is_detected_before_any_firmware_command(
    monkeypatch,
) -> None:
    calls: list[tuple[str, list[str]]] = []

    def stream(_services, port, args, **_kwargs):
        calls.append((port, list(args)))
        return _completed(list(args), 0)

    hardening, _runtime = _reload_hardening(monkeypatch, stream)
    physical = "F0:9E:9E:76:07:10"
    sessions = Sessions({"COM9": Fingerprint("COM9", physical, "1-3")})
    services = _services(sessions, lambda *_a, **_kw: "COM9")

    result = hardening.prepare_s3_download_mode(services, "COM9", "tracker")

    assert result == "COM9"
    assert services._jarnsen_s3_rom_last_path == "manual-rom"
    assert len(calls) == 1
    assert calls[0][1] == [
        "--chip",
        "esp32s3",
        "--before",
        "no-reset",
        "--after",
        "no-reset",
        "read-flash-status",
    ]


def test_tracker_build185_service_enters_rom_and_rebinds_same_physical_usb(
    monkeypatch,
) -> None:
    calls: list[tuple[str, list[str]]] = []
    raw_calls: list[str] = []

    def stream(_services, port, args, **_kwargs):
        calls.append((port, list(args)))
        # Application-mode passive probe fails; post-service ROM probe succeeds.
        return _completed(list(args), 0 if port == "COM10" else 2)

    def raw_command(_port, command, *, expected, timeout):
        raw_calls.append(command)
        if command == "JARNSEN_TOOL_INFO":
            assert expected == "===JARNSEN_INFO==="
            return (
                "===JARNSEN_INFO=== product=JARNSEN-MESH build=185 "
                "role_api=1 rom_boot=1"
            )
        assert command == "JARNSEN_TOOL_ROM_BOOT"
        assert expected == "===JARNSEN_ROM_BOOT==="
        return "===JARNSEN_ROM_BOOT=== accepted=1 chip=esp32s3"

    hardening, _runtime = _reload_hardening(monkeypatch, stream, raw_command)
    physical = "F0:9E:9E:76:07:10"
    sessions = Sessions(
        {
            "COM9": Fingerprint("COM9", physical, "1-3"),
            "COM10": Fingerprint("COM10", physical, "1-3"),
        }
    )
    services = _services(sessions, lambda *_a, **_kw: "COM10")

    result = hardening.prepare_s3_download_mode(services, "COM9", "tracker")

    assert result == "COM10"
    assert raw_calls == ["JARNSEN_TOOL_INFO", "JARNSEN_TOOL_ROM_BOOT"]
    assert services._jarnsen_s3_rom_last_path == "firmware-service"
    assert calls[0][0] == "COM9"
    assert calls[1][0] == "COM10"
    assert all(
        call[1][2:6] == ["--before", "no-reset", "--after", "no-reset"]
        for call in calls
    )


def test_tracker_old_or_foreign_firmware_requires_manual_user_reset(
    monkeypatch,
) -> None:
    calls: list[tuple[str, list[str]]] = []

    def stream(_services, port, args, **_kwargs):
        calls.append((port, list(args)))
        return _completed(list(args), 2, "No serial data received")

    def raw_command(_port, command, *, expected, timeout):
        assert command == "JARNSEN_TOOL_INFO"
        return "===JARNSEN_INFO=== product=JARNSEN-MESH build=184 role_api=1"

    hardening, _runtime = _reload_hardening(monkeypatch, stream, raw_command)
    sessions = Sessions({"COM9": Fingerprint("COM9", "F0:9E:9E:76:07:10", "1-3")})
    services = _services(sessions, lambda *_a, **_kw: "COM9")

    with pytest.raises(RuntimeError, match="S3_MANUAL_BOOT_REQUIRED") as error:
        hardening.prepare_s3_download_mode(services, "COM9", "tracker")

    text = str(error.value)
    assert "USER" in text and "RESET" in text
    assert len(calls) == 1
    assert "erase-flash" not in calls[0][1]
    assert "write-flash" not in calls[0][1]


def test_tracker_service_blocks_different_physical_usb_after_reenumeration(
    monkeypatch,
) -> None:
    calls: list[tuple[str, list[str]]] = []

    def stream(_services, port, args, **_kwargs):
        calls.append((port, list(args)))
        return _completed(list(args), 2)

    def raw_command(_port, command, *, expected, timeout):
        if command == "JARNSEN_TOOL_INFO":
            return "===JARNSEN_INFO=== build=185 rom_boot=1"
        return "===JARNSEN_ROM_BOOT=== accepted=1 chip=esp32s3"

    hardening, _runtime = _reload_hardening(monkeypatch, stream, raw_command)
    sessions = Sessions(
        {
            "COM9": Fingerprint("COM9", "F0:9E:9E:76:07:10", "1-3"),
            "COM10": Fingerprint("COM10", "AA:BB:CC:DD:EE:FF", "1-4"),
        }
    )
    services = _services(sessions, lambda *_a, **_kw: "COM10")

    with pytest.raises(RuntimeError, match="S3_PHYSICAL_ID_MISMATCH"):
        hardening.prepare_s3_download_mode(services, "COM9", "tracker")

    # No ROM probe and no destructive command is allowed on the wrong device.
    assert len(calls) == 1
    assert calls[0][0] == "COM9"


def test_prepare_requires_strong_physical_identity(monkeypatch) -> None:
    calls: list[tuple[str, list[str]]] = []

    def stream(_services, port, args, **_kwargs):
        calls.append((port, list(args)))
        return _completed(list(args))

    hardening, _runtime = _reload_hardening(monkeypatch, stream)
    sessions = Sessions(
        {
            "COM9": Fingerprint(
                "COM9", "", "", vid=0x303A, pid=0x1001, hwid="USB VID:PID=303A:1001"
            )
        }
    )
    services = _services(sessions, lambda *_a, **_kw: "COM9")

    with pytest.raises(RuntimeError, match="S3_PHYSICAL_ID_REQUIRED"):
        hardening.prepare_s3_download_mode(services, "COM9", "tracker")

    assert calls == []


def test_v3_keeps_bridge_default_reset_path(monkeypatch) -> None:
    calls: list[tuple[str, list[str]]] = []

    def stream(_services, port, args, **_kwargs):
        values = list(args)
        calls.append((port, values))
        return _completed(values, 0)

    hardening, _runtime = _reload_hardening(monkeypatch, stream)
    sessions = Sessions(
        {
            "COM7": Fingerprint(
                "COM7", "V3-UNIT-01", "2-1", vid=0x10C4, pid=0xEA60
            )
        }
    )
    services = _services(sessions, lambda *_a, **_kw: "COM7")

    result = hardening.prepare_s3_download_mode(services, "COM7", "repeater")

    assert result == "COM7"
    assert services._jarnsen_s3_rom_last_path == "bridge-reset"
    assert calls[0][1][:6] == [
        "--chip", "esp32s3", "--before", "default-reset", "--after", "no-reset"
    ]
    assert calls[1][1][:6] == [
        "--chip", "esp32s3", "--before", "no-reset", "--after", "no-reset"
    ]


def test_install_keeps_destructive_tracker_chain_no_reset_after_manual_rom(
    monkeypatch,
) -> None:
    events: list[tuple[str, str, list[str]]] = []

    def base_stream(_services, port, args, **_kwargs):
        values = list(args)
        events.append(("esptool", port, values))
        return _completed(values, 0)

    hardening, fake_runtime = _reload_hardening(monkeypatch, base_stream)
    physical = "F0:9E:9E:76:07:10"
    sessions = Sessions({"COM9": Fingerprint("COM9", physical, "1-3")})
    services = _services(sessions, lambda *_a, **_kw: "COM9")
    services.BOARD_PROFILES = {"tracker": {"flash_strategy": "dual_slot"}}

    def base_flash_bundle(port, _bundle, log=None):
        for args in (
            ["erase-flash"],
            ["--baud", "921600", "write-flash", "0x0", "factory.bin"],
            ["run"],
        ):
            fake_runtime._stream_esptool(
                services,
                port,
                args,
                timeout=1,
                stage="test",
                phase_start=0.0,
                phase_end=1.0,
                log=log,
                check=False,
            )

    services.flash_bundle = base_flash_bundle
    hardening.install(services)
    bundle = types.SimpleNamespace(board_key="tracker", flash_strategy="dual_slot")
    services.flash_bundle("COM9", bundle)

    destructive = [
        (port, args)
        for _kind, port, args in events
        if "erase-flash" in args or "write-flash" in args or "run" in args
    ]
    assert len(destructive) == 3
    for port, args in destructive:
        assert port == "COM9"
        assert args[:6] == [
            "--chip", "esp32s3", "--before", "no-reset", "--after", "no-reset"
        ]
    assert services._jarnsen_s3_rom_hardening is True
