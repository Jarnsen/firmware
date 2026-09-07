from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import serial

import radio_profiles


RADIO_INFO_MARKER = "===JARNSEN_RADIO==="
RADIO_OK_MARKER = "===JARNSEN_RADIO_OK==="
RADIO_ERROR_MARKER = "===JARNSEN_RADIO_ERROR==="
ACTIVE_RE = re.compile(r"\bactive=(standard|jarnsen1|jarnsen2)\b", re.IGNORECASE)


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _raw_command(port: str, command: str, *, expected: str, timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    buffer = bytearray()
    with serial.Serial(port=port, baudrate=115200, timeout=0.12, write_timeout=2.0) as ser:
        try:
            ser.reset_input_buffer()
        except Exception:
            pass
        time.sleep(0.20)
        payload = (command.rstrip() + "\n").encode("ascii", errors="strict")
        ser.write(payload)
        ser.flush()
        _emit(f"RADIO NODE SYNC command={command!r} port={port}")

        while time.monotonic() < deadline:
            chunk = ser.read(512)
            if chunk:
                buffer.extend(chunk)
                text = buffer.decode("utf-8", errors="replace")
                for line in text.replace("\r", "\n").split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith(RADIO_ERROR_MARKER):
                        raise RuntimeError(line)
                    if line.startswith(expected):
                        _emit(f"RADIO NODE SYNC response={line!r} port={port}")
                        return line
            else:
                time.sleep(0.03)

    seen = buffer.decode("utf-8", errors="replace")[-600:]
    raise TimeoutError(
        f"Keine Antwort auf {command!r} von {port}. "
        f"Die installierte Firmware unterstützt die 3 Funkprofil-Slots möglicherweise noch nicht. "
        f"Empfangen: {seen!r}"
    )


def _reboot_to_raw(port: str, services: Any) -> None:
    try:
        services.reboot_node(port)
    except Exception as exc:
        _emit(f"RADIO NODE SYNC reboot-warning port={port} type={type(exc).__name__} message={exc}")
    services.wait_for_serial(port, timeout=90)
    time.sleep(1.0)


def _read_active_profile(port: str, services: Any) -> str:
    _reboot_to_raw(port, services)
    line = _raw_command(port, "JARNSEN_TOOL_RADIO_INFO", expected=RADIO_INFO_MARKER)
    match = ACTIVE_RE.search(line)
    if not match:
        raise RuntimeError(f"Aktives Funkprofil konnte nicht aus der Firmware-Antwort gelesen werden: {line}")
    active = match.group(1).lower()
    _emit(f"RADIO NODE SYNC active-before={active} port={port}")
    return active


def _frequency_for(settings: dict[str, Any], profile: str) -> str:
    if profile == radio_profiles.PROFILE_JARNSEN_1:
        key = "jarnsen_1_mhz"
        fallback = radio_profiles.JARNSEN_FREQUENCIES[profile]
    else:
        key = "jarnsen_2_mhz"
        fallback = radio_profiles.JARNSEN_FREQUENCIES[profile]
    value = settings.get(key, fallback)
    return f"{float(value):.3f}"


def _write_firmware_slots(port: str, settings: dict[str, Any], active_before: str, services: Any) -> None:
    _reboot_to_raw(port, services)
    _raw_command(
        port,
        "JARNSEN_TOOL_RADIO_CAPTURE_STANDARD",
        expected=RADIO_OK_MARKER,
    )

    for profile in (radio_profiles.PROFILE_JARNSEN_1, radio_profiles.PROFILE_JARNSEN_2):
        frequency = _frequency_for(settings, profile)
        modem = radio_profiles.modem_preset_for(settings, profile) or "LONG_FAST"
        hops = radio_profiles.hop_limit_for(settings, profile)
        _raw_command(
            port,
            f"JARNSEN_TOOL_RADIO_SET {profile} {frequency} {modem} {hops}",
            expected=RADIO_OK_MARKER,
        )

    target = active_before if active_before in radio_profiles.PROFILE_KEYS else radio_profiles.PROFILE_STANDARD
    _raw_command(
        port,
        f"JARNSEN_TOOL_RADIO_SELECT {target}",
        expected=RADIO_OK_MARKER,
    )

    # The firmware schedules a reboot after SELECT. Wait until it has had time
    # to execute and then verify the same profile is active again.
    time.sleep(2.0)
    services.wait_for_serial(port, timeout=90)
    time.sleep(0.8)
    line = _raw_command(port, "JARNSEN_TOOL_RADIO_INFO", expected=RADIO_INFO_MARKER)
    match = ACTIVE_RE.search(line)
    active_after = match.group(1).lower() if match else ""
    if active_after != target:
        raise RuntimeError(
            f"Funkprofil-Verifikation fehlgeschlagen: erwartet {target}, Firmware meldet {active_after or line}"
        )
    _emit(
        "RADIO NODE SYNC complete "
        f"port={port} standard=1 jarnsen1=1 jarnsen2=1 active-before={active_before} active-after={active_after}"
    )


def install(services: Any) -> None:
    """Write all three radio profiles into firmware slots while preserving the node's active selection."""
    if getattr(services, "_jarnsen_radio_profile_node_sync_installed", False):
        return
    services._jarnsen_radio_profile_node_sync_installed = True

    base_restore = services.restore_profile

    def restore_profile(port: str, profile: Path | None = None) -> None:
        settings = dict(services.load_radio_profile_settings())
        active_before = _read_active_profile(port, services)

        # radio_profiles.restore_profile historically staged only the currently
        # selected overlay. Force that wrapper to write Standard to config.lora;
        # the two JARNSEN variants are stored separately afterwards.
        original_load = radio_profiles.load_settings
        forced_standard = dict(settings)
        forced_standard["selected"] = radio_profiles.PROFILE_STANDARD
        radio_profiles.load_settings = lambda _services: dict(forced_standard)
        try:
            base_restore(port, profile)
        finally:
            radio_profiles.load_settings = original_load

        _write_firmware_slots(port, settings, active_before, services)

    services.restore_profile = restore_profile
    services.sync_radio_profiles_to_node = lambda port: _write_firmware_slots(
        port,
        dict(services.load_radio_profile_settings()),
        _read_active_profile(port, services),
        services,
    )

    _emit(
        "RADIO NODE SYNC installed slots=standard,jarnsen1,jarnsen2 preserve-active=1 "
        "standard-via-profile=1 jarnsen-via-firmware-service=1 verification=1"
    )
