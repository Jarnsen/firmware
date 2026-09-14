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


def _reload_hardening(monkeypatch, stream):
    fake_runtime = types.ModuleType("flash_runtime")
    fake_runtime._stream_esptool = stream
    monkeypatch.setitem(sys.modules, "flash_runtime", fake_runtime)
    import s3_rom_hardening

    hardening = importlib.reload(s3_rom_hardening)
    return hardening, fake_runtime


def _completed(args: list[str] | None = None, returncode: int = 0):
    return subprocess.CompletedProcess(args or ["esptool"], returncode, "ROM OK", "")


@pytest.mark.parametrize("board_key", ["tracker", "repeater"])
def test_prepare_native_s3_rebinds_only_same_physical_usb(
    monkeypatch, board_key: str
) -> None:
    calls: list[tuple[str, list[str]]] = []

    def stream(_services, port, args, **_kwargs):
        calls.append((port, list(args)))
        return _completed(list(args))

    hardening, _runtime = _reload_hardening(monkeypatch, stream)
    physical = "F0:9E:9E:76:07:10"
    sessions = Sessions(
        {
            "COM9": Fingerprint("COM9", physical, "1-3"),
            "COM10": Fingerprint("COM10", physical, "1-3"),
        }
    )
    services = types.SimpleNamespace(
        FlasherError=RuntimeError,
        device_sessions=sessions,
        wait_for_device_reconnect=lambda *_a, **_kw: "COM10",
    )

    result = hardening.prepare_s3_download_mode(services, "COM9", board_key)

    assert result == "COM10"
    assert len(calls) == 2
    assert calls[0][0] == "COM9"
    assert calls[0][1] == [
        "--chip",
        "esp32s3",
        "--before",
        "usb-reset",
        "--after",
        "no-reset",
        "read-flash-status",
    ]
    assert calls[1][0] == "COM10"
    assert calls[1][1] == [
        "--chip",
        "esp32s3",
        "--before",
        "no-reset",
        "--after",
        "no-reset",
        "read-flash-status",
    ]


def test_prepare_native_s3_blocks_same_vidpid_with_different_serial(
    monkeypatch,
) -> None:
    calls: list[tuple[str, list[str]]] = []

    def stream(_services, port, args, **_kwargs):
        calls.append((port, list(args)))
        return _completed(list(args))

    hardening, _runtime = _reload_hardening(monkeypatch, stream)
    sessions = Sessions(
        {
            "COM9": Fingerprint("COM9", "F0:9E:9E:76:07:10", "1-3"),
            "COM10": Fingerprint("COM10", "AA:BB:CC:DD:EE:FF", "1-4"),
        }
    )
    services = types.SimpleNamespace(
        FlasherError=RuntimeError,
        device_sessions=sessions,
        wait_for_device_reconnect=lambda *_a, **_kw: "COM10",
    )

    with pytest.raises(RuntimeError, match="S3_PHYSICAL_ID_MISMATCH"):
        hardening.prepare_s3_download_mode(services, "COM9", "tracker")

    # Only the non-destructive USB-reset probe was allowed. The ROM readback on
    # the wrong device and every erase/write command remain blocked.
    assert len(calls) == 1
    assert "erase-flash" not in calls[0][1]
    assert "write-flash" not in calls[0][1]


def test_prepare_native_s3_requires_strong_physical_identity(monkeypatch) -> None:
    calls: list[tuple[str, list[str]]] = []

    def stream(_services, port, args, **_kwargs):
        calls.append((port, list(args)))
        return _completed(list(args))

    hardening, _runtime = _reload_hardening(monkeypatch, stream)
    sessions = Sessions(
        {
            "COM9": Fingerprint(
                "COM9",
                "",
                "",
                vid=0x303A,
                pid=0x1001,
                hwid="USB VID:PID=303A:1001",
            )
        }
    )
    services = types.SimpleNamespace(
        FlasherError=RuntimeError,
        device_sessions=sessions,
        wait_for_device_reconnect=lambda *_a, **_kw: "COM9",
    )

    with pytest.raises(RuntimeError, match="S3_PHYSICAL_ID_REQUIRED"):
        hardening.prepare_s3_download_mode(services, "COM9", "tracker")

    assert calls == []


def test_v3_bridge_uses_default_reset_before_rom_probe(monkeypatch) -> None:
    calls: list[tuple[str, list[str]]] = []

    def stream(_services, port, args, **_kwargs):
        calls.append((port, list(args)))
        return _completed(list(args))

    hardening, _runtime = _reload_hardening(monkeypatch, stream)
    sessions = Sessions(
        {
            "COM7": Fingerprint(
                "COM7",
                "V3-UNIT-01",
                "2-1",
                vid=0x10C4,
                pid=0xEA60,
            )
        }
    )
    services = types.SimpleNamespace(
        FlasherError=RuntimeError,
        device_sessions=sessions,
        wait_for_device_reconnect=lambda *_a, **_kw: "COM7",
    )

    result = hardening.prepare_s3_download_mode(services, "COM7", "repeater")

    assert result == "COM7"
    assert calls[0][1][:6] == [
        "--chip",
        "esp32s3",
        "--before",
        "default-reset",
        "--after",
        "no-reset",
    ]
    assert calls[1][1][:6] == [
        "--chip",
        "esp32s3",
        "--before",
        "no-reset",
        "--after",
        "no-reset",
    ]


@pytest.mark.parametrize("board_key", ["tracker", "repeater"])
def test_install_prepares_rom_before_first_destructive_command(
    monkeypatch, board_key: str
) -> None:
    events: list[tuple[str, str, list[str]]] = []

    def base_stream(_services, port, args, **_kwargs):
        values = list(args)
        events.append(("esptool", port, values))
        return _completed(values)

    hardening, fake_runtime = _reload_hardening(monkeypatch, base_stream)
    physical = "F0:9E:9E:76:07:10"
    sessions = Sessions(
        {
            "COM9": Fingerprint("COM9", physical, "1-3"),
            "COM10": Fingerprint("COM10", physical, "1-3"),
        }
    )

    services = types.SimpleNamespace(
        FlasherError=RuntimeError,
        device_sessions=sessions,
        wait_for_device_reconnect=lambda *_a, **_kw: "COM10",
        BOARD_PROFILES={board_key: {"flash_strategy": "dual_slot"}},
    )

    def base_flash_bundle(port, _bundle, log=None):
        fake_runtime._stream_esptool(
            services,
            port,
            ["erase-flash"],
            timeout=1,
            stage="erase",
            phase_start=0.0,
            phase_end=0.1,
            log=log,
        )
        fake_runtime._stream_esptool(
            services,
            port,
            ["--baud", "921600", "write-flash", "0x0", "factory.bin"],
            timeout=1,
            stage="write",
            phase_start=0.1,
            phase_end=0.9,
            log=log,
        )
        fake_runtime._stream_esptool(
            services,
            port,
            ["run"],
            timeout=1,
            stage="run",
            phase_start=0.9,
            phase_end=1.0,
            log=log,
            check=False,
        )

    services.flash_bundle = base_flash_bundle
    hardening.install(services)
    bundle = types.SimpleNamespace(board_key=board_key, flash_strategy="dual_slot")
    services.flash_bundle("COM9", bundle)

    commands = [
        next(
            (
                value
                for value in args
                if value
                in {
                    "read-flash-status",
                    "erase-flash",
                    "write-flash",
                    "run",
                }
            ),
            "",
        )
        for _kind, _port, args in events
    ]
    assert commands[:3] == ["read-flash-status", "read-flash-status", "erase-flash"]

    destructive = [
        (port, args)
        for _kind, port, args in events
        if "erase-flash" in args or "write-flash" in args or "run" in args
    ]
    assert destructive
    for port, args in destructive:
        assert port == "COM10"
        assert args[:6] == [
            "--chip",
            "esp32s3",
            "--before",
            "no-reset",
            "--after",
            "no-reset",
        ]

    assert services._jarnsen_s3_rom_hardening is True
