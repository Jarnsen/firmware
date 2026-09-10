from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from serial.tools import list_ports


COMMON_FEATURES = (
    "board_detection",
    "manual_board_fallback",
    "firmware_identity",
    "github_update_resolution",
    "backup",
    "automatic_flash",
    "firmware_only",
    "local_firmware",
    "profile_read",
    "profile_write",
    "role_choice",
    "role_readback",
    "name_choice",
    "name_write",
    "name_readback",
    "reboot_reconnect",
    "usb_node_log",
    "radio_profiles",
    "series_flash",
    "final_verify",
    "serial_arbitration",
)


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


@dataclass(frozen=True)
class BoardCapability:
    key: str
    label: str
    pio_env: str
    artifact_kind: str
    flash_transport: str
    features: tuple[str, ...] = COMMON_FEATURES


@dataclass(frozen=True)
class DeviceFingerprint:
    port: str
    serial_number: str
    location: str
    vid: int | None
    pid: int | None
    hwid: str
    description: str


class DeviceSessionManager:
    """Capability/reconnect manager for all supported boards.

    IMPORTANT: low-level serial arbitration stays owned by unified_service_v2.
    This manager must not wrap services.meshtastic or replace jarnsen_serial_guard.
    The previous double wrapping created nested device sessions around every
    Meshtastic probe and regressed real Windows USB/COM access on Tracker/V3.
    """

    def __init__(self, services: Any) -> None:
        self.services = services
        self._registry_lock = threading.RLock()
        self._locks: dict[str, threading.RLock] = {}
        self._aliases: dict[str, str] = {}
        self._fingerprints: dict[str, DeviceFingerprint] = {}
        self._owners: dict[str, tuple[str, int, float]] = {}

    @staticmethod
    def _key(port: str) -> str:
        return str(port or "").strip().upper()

    def _lock_for(self, port: str) -> threading.RLock:
        key = self._key(port)
        with self._registry_lock:
            return self._locks.setdefault(key, threading.RLock())

    def resolve_port(self, port: str) -> str:
        current = str(port or "").strip()
        seen: set[str] = set()
        while current:
            key = self._key(current)
            if key in seen:
                break
            seen.add(key)
            with self._registry_lock:
                next_port = self._aliases.get(key)
            if not next_port or self._key(next_port) == key:
                break
            current = next_port
        return current or str(port or "").strip()

    def _read_fingerprint(self, port: str) -> DeviceFingerprint | None:
        wanted = self._key(port)
        for item in list_ports.comports():
            if self._key(item.device) != wanted:
                continue
            return DeviceFingerprint(
                port=str(item.device),
                serial_number=str(getattr(item, "serial_number", "") or ""),
                location=str(getattr(item, "location", "") or ""),
                vid=getattr(item, "vid", None),
                pid=getattr(item, "pid", None),
                hwid=str(getattr(item, "hwid", "") or ""),
                description=str(getattr(item, "description", "") or ""),
            )
        return None

    def remember(self, port: str) -> DeviceFingerprint | None:
        live = self.resolve_port(port)
        fingerprint = self._read_fingerprint(live)
        if fingerprint is not None:
            with self._registry_lock:
                self._fingerprints[self._key(port)] = fingerprint
                self._fingerprints[self._key(live)] = fingerprint
        return fingerprint

    @staticmethod
    def _score(expected: DeviceFingerprint, candidate: DeviceFingerprint) -> int:
        score = 0
        if expected.serial_number and candidate.serial_number == expected.serial_number:
            score += 100
        if expected.location and candidate.location == expected.location:
            score += 60
        if expected.vid is not None and expected.pid is not None:
            if candidate.vid == expected.vid and candidate.pid == expected.pid:
                score += 25
        if expected.hwid and candidate.hwid == expected.hwid:
            score += 20
        if expected.description and candidate.description == expected.description:
            score += 5
        return score

    @contextmanager
    def guard(self, port: str, purpose: str = "device-session"):
        """Optional high-level guard only.

        Runtime serial/CLI calls deliberately do not use this automatically.
        unified_service_v2._serial_guard remains the one low-level authority.
        """
        live = self.resolve_port(port)
        lock = self._lock_for(live)
        started = time.monotonic()
        lock.acquire()
        key = self._key(live)
        try:
            self.remember(live)
            with self._registry_lock:
                self._owners[key] = (str(purpose), threading.get_ident(), started)
            _emit(f"DEVICE SESSION ACQUIRE port={live} purpose={purpose!r}")
            yield live
        finally:
            elapsed = time.monotonic() - started
            with self._registry_lock:
                owner = self._owners.get(key)
                if owner and owner[1] == threading.get_ident():
                    self._owners.pop(key, None)
            lock.release()
            _emit(f"DEVICE SESSION RELEASE port={live} purpose={purpose!r} duration={elapsed:.3f}s")

    @contextmanager
    def guard_compat(self, port: str):
        with self.guard(port, "device-session") as live:
            yield live

    def owner(self, port: str) -> str | None:
        live = self.resolve_port(port)
        with self._registry_lock:
            value = self._owners.get(self._key(live))
        return value[0] if value else None

    def wait_for_reconnect(
        self,
        port: str,
        timeout: int = 90,
        *,
        expected_board: str | None = None,
    ) -> str:
        original = str(port or "").strip()
        original_key = self._key(original)
        expected = self._fingerprints.get(original_key) or self.remember(original)
        deadline = time.monotonic() + max(1, int(timeout))
        last_ports: tuple[str, ...] = ()

        while time.monotonic() < deadline:
            candidates: list[DeviceFingerprint] = []
            for item in list_ports.comports():
                bluetooth_check = getattr(self.services, "is_bluetooth_serial", None)
                if callable(bluetooth_check) and bluetooth_check(item):
                    continue
                candidates.append(
                    DeviceFingerprint(
                        port=str(item.device),
                        serial_number=str(getattr(item, "serial_number", "") or ""),
                        location=str(getattr(item, "location", "") or ""),
                        vid=getattr(item, "vid", None),
                        pid=getattr(item, "pid", None),
                        hwid=str(getattr(item, "hwid", "") or ""),
                        description=str(getattr(item, "description", "") or ""),
                    )
                )

            same = next((item for item in candidates if self._key(item.port) == original_key), None)
            selected: DeviceFingerprint | None = same
            reason = "same-port" if same is not None else ""

            if selected is None and expected is not None and candidates:
                ranked = sorted(
                    ((self._score(expected, item), item) for item in candidates),
                    key=lambda pair: pair[0],
                    reverse=True,
                )
                if ranked and ranked[0][0] >= 25:
                    selected = ranked[0][1]
                    reason = f"fingerprint:{ranked[0][0]}"

            # Native USB may return with a different PID/COM in download mode;
            # one Espressif device is the only safe automatic Supreme target.
            if selected is None and str(expected_board or "").lower() == "tbeam_supreme":
                espressif = [item for item in candidates if item.vid == 0x303A]
                if len(espressif) == 1:
                    selected = espressif[0]
                    reason = "single-espressif-usb"

            if selected is not None:
                live = selected.port
                with self._registry_lock:
                    self._aliases[original_key] = live
                    self._fingerprints[original_key] = selected
                    self._fingerprints[self._key(live)] = selected
                _emit(
                    f"DEVICE RECONNECT original={original} live={live} reason={reason} "
                    f"board={expected_board or ''!r}"
                )
                time.sleep(2.0)
                return live

            ports = tuple(sorted(item.port for item in candidates))
            if ports != last_ports:
                last_ports = ports
                _emit(f"DEVICE RECONNECT WAIT original={original} visible={ports!r}")
            time.sleep(0.5)

        raise self.services.FlasherError(
            f"{original} bzw. dasselbe USB-Gerät ist nach {timeout}s nicht wieder erschienen."
        )


def _capabilities(services: Any) -> dict[str, BoardCapability]:
    result: dict[str, BoardCapability] = {}
    for key, profile in services.BOARD_PROFILES.items():
        artifact_kind = str(profile.get("artifact_kind") or "esp32").lower()
        result[key] = BoardCapability(
            key=key,
            label=str(profile.get("label") or key),
            pio_env=str(profile.get("pio_env") or ""),
            artifact_kind=artifact_kind,
            flash_transport="uf2" if artifact_kind == "uf2" else "esptool",
        )
    return result


def install(services: Any) -> None:
    if getattr(services, "_jarnsen_device_core_v1", False):
        return

    manager = DeviceSessionManager(services)
    services.device_sessions = manager
    services.BOARD_CAPABILITIES = _capabilities(services)
    services.board_capabilities = lambda board_key: services.BOARD_CAPABILITIES[board_key]
    services.board_capability_matrix = lambda: {
        key: {feature: True for feature in capability.features}
        for key, capability in services.BOARD_CAPABILITIES.items()
    }
    services.resolve_live_port = manager.resolve_port
    services.wait_for_device_reconnect = manager.wait_for_reconnect

    # Keep the proven SERIAL ARBITRATION V2 layer as the single low-level owner.
    # Do NOT wrap services.meshtastic again and do NOT replace
    # services.jarnsen_serial_guard / unified_service_v2._serial_guard.
    # The device core is responsible for capabilities + reconnect identity only.
    base_wait_for_serial = services.wait_for_serial

    def wait_for_serial(port: str, timeout: int = 90) -> None:
        try:
            manager.wait_for_reconnect(port, timeout=timeout)
            return
        except Exception as reconnect_error:
            _emit(
                f"DEVICE RECONNECT FALLBACK port={port} "
                f"error={type(reconnect_error).__name__}:{reconnect_error}"
            )
        base_wait_for_serial(manager.resolve_port(port), timeout=timeout)

    services.wait_for_serial = wait_for_serial
    services._jarnsen_device_core_v1 = True
    services._jarnsen_device_core_low_level_passthrough = True
    _emit(
        "DEVICE CORE installed boards="
        + str(len(services.BOARD_CAPABILITIES))
        + " common-features="
        + str(len(COMMON_FEATURES))
        + " session-manager=1 reconnect-alias=1 low-level-passthrough=1 "
        + "serial-arbitration-v2-remains-authoritative=1"
    )
