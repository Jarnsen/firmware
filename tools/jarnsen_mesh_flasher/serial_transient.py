from __future__ import annotations

import subprocess
import threading
import time
from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _decode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def install(services: Any) -> None:
    """Remember short USB appearances and follow the physical device.

    Some native-USB nodes enumerate a COM port only briefly while booting or
    switching power state.  The stable scanner intentionally ignores a single
    sighting, so this layer remembers the physical USB fingerprint and chases
    that same device across COM-number changes without ever guessing a board
    from a generic VID/PID.
    """

    base_scan = services.scan_devices
    original_comports = services.list_ports.comports
    bluetooth_test = getattr(services, "is_bluetooth_serial", None)
    fingerprint_fn = getattr(services, "serial_device_fingerprint", None)
    usb_hint_fn = getattr(services, "usb_board_hint", None)

    cache: dict[str, dict[str, Any]] = {}
    lock = threading.RLock()
    ttl_seconds = 12.0

    def fingerprint(item: Any) -> str:
        try:
            if callable(fingerprint_fn):
                value = fingerprint_fn(item)
                if value:
                    return str(value)
        except Exception:
            pass
        port = str(getattr(item, "device", "") or "").upper()
        hwid = str(getattr(item, "hwid", "") or "")
        return f"fallback:{port}:{hwid}"

    def is_bluetooth(item: Any) -> bool:
        try:
            return bool(callable(bluetooth_test) and bluetooth_test(item))
        except Exception:
            return False

    def note_transient(item: Any, *, source: str = "enumeration") -> str | None:
        if item is None or is_bluetooth(item):
            return None
        port = str(getattr(item, "device", "") or "").upper()
        if not port:
            return None
        fp = fingerprint(item)
        now = time.monotonic()
        with lock:
            entry = cache.get(fp)
            if entry is None:
                entry = {
                    "fingerprint": fp,
                    "first_seen": now,
                    "last_seen": now,
                    "last_port": port,
                    "item": item,
                    "sightings": 1,
                    "board_key": None,
                    "model_text": "",
                }
                cache[fp] = entry
                _emit(
                    f"SERIAL TRANSIENT SEEN source={source} port={port} fp={fp!r} sightings=1"
                )
            else:
                old_port = str(entry.get("last_port") or "")
                entry["last_seen"] = now
                entry["last_port"] = port
                entry["item"] = item
                entry["sightings"] = int(entry.get("sightings", 0)) + 1
                if old_port != port:
                    _emit(
                        f"SERIAL TRANSIENT RENUMBER source={source} fp={fp!r} "
                        f"old_port={old_port} new_port={port} sightings={entry['sightings']}"
                    )
        return fp

    def tracked_comports():
        items = list(original_comports())
        for item in items:
            note_transient(item, source="comports")
        return items

    # Every scanner/hotplug enumeration now feeds the transient cache.  Keep the
    # original function for the chase loop so recording does not recurse.
    services.list_ports.comports = tracked_comports
    services.serial_note_transient = note_transient

    def current_match(fp: str) -> Any | None:
        try:
            items = list(original_comports())
        except Exception as exc:
            _emit(f"SERIAL TRANSIENT ENUM ERROR type={type(exc).__name__} message={exc}")
            return None
        for item in items:
            if is_bluetooth(item):
                continue
            note_transient(item, source="chase")
            if fingerprint(item) == fp:
                return item
        return None

    def port_present(port: str, fp: str) -> bool:
        item = current_match(fp)
        return bool(item is not None and str(getattr(item, "device", "") or "").upper() == port)

    def recent_entries() -> list[dict[str, Any]]:
        now = time.monotonic()
        with lock:
            expired = [fp for fp, entry in cache.items() if now - float(entry.get("last_seen", 0.0)) > ttl_seconds]
            for fp in expired:
                entry = cache.pop(fp, None)
                if entry:
                    _emit(
                        f"SERIAL TRANSIENT EXPIRED port={entry.get('last_port')} fp={fp!r} "
                        f"sightings={entry.get('sightings', 0)}"
                    )
            return sorted(
                (dict(entry) for entry in cache.values()),
                key=lambda entry: float(entry.get("last_seen", 0.0)),
                reverse=True,
            )

    def learn_from_devices(devices: list[Any]) -> None:
        if not devices:
            return
        try:
            items = list(original_comports())
        except Exception:
            items = []
        item_by_port = {
            str(getattr(item, "device", "") or "").upper(): item
            for item in items
            if not is_bluetooth(item)
        }
        with lock:
            for device in devices:
                port = str(getattr(device, "port", "") or "").upper()
                item = item_by_port.get(port)
                if item is None:
                    continue
                fp = fingerprint(item)
                entry = cache.get(fp)
                if entry is None:
                    continue
                board_key = getattr(device, "board_key", None)
                model_text = str(getattr(device, "model_text", "") or "")
                if board_key:
                    entry["board_key"] = board_key
                if model_text:
                    entry["model_text"] = model_text
                _emit(
                    f"SERIAL TRANSIENT LEARNED port={port} fp={fp!r} "
                    f"board={entry.get('board_key')!r}"
                )

    def probe_reappearance(entry: dict[str, Any], *, chase_seconds: float = 8.0):
        fp = str(entry.get("fingerprint") or "")
        if not fp:
            return None
        deadline = time.monotonic() + chase_seconds
        last_port = str(entry.get("last_port") or "")
        _emit(
            f"SERIAL TRANSIENT TRACK fp={fp!r} last_port={last_port} "
            f"age={time.monotonic()-float(entry.get('last_seen', 0.0)):.3f}s chase={chase_seconds:.1f}s"
        )

        attempt = 0
        while time.monotonic() < deadline:
            item = current_match(fp)
            if item is None:
                time.sleep(0.10)
                continue

            port = str(getattr(item, "device", "") or "").upper()
            if not port:
                time.sleep(0.10)
                continue
            if port != last_port:
                _emit(f"SERIAL TRANSIENT REAPPEARED fp={fp!r} old_port={last_port} new_port={port}")
                last_port = port

            # Require a tiny 100 ms physical hold, not two 350/700 ms GUI polls.
            time.sleep(0.10)
            if not port_present(port, fp):
                _emit(f"SERIAL TRANSIENT FLASH port={port} fp={fp!r} visible_lt=100ms")
                continue

            attempt += 1
            _emit(f"SERIAL TRANSIENT PROBE attempt={attempt} port={port} fp={fp!r}")
            info_text = ""
            try:
                proc = services.meshtastic(port, "--info", timeout=6, check=False)
                info_text = "\n".join(filter(None, (proc.stdout, proc.stderr)))
            except subprocess.TimeoutExpired as exc:
                info_text = "\n".join(filter(None, (_decode(exc.stdout), _decode(exc.stderr))))
                _emit(
                    f"SERIAL TRANSIENT PROBE TIMEOUT port={port} chars={len(info_text)} partial=1"
                )
            except Exception as exc:
                info_text = "\n".join(
                    filter(None, (_decode(getattr(exc, "stdout", "")), _decode(getattr(exc, "stderr", ""))))
                )
                _emit(
                    f"SERIAL TRANSIENT PROBE ERROR port={port} type={type(exc).__name__} "
                    f"message={exc} chars={len(info_text)}"
                )

            board_key = services.detect_board_from_text(info_text) if info_text else None
            usb_hint = None
            try:
                if callable(usb_hint_fn):
                    usb_hint, _reason = usb_hint_fn(item)
            except Exception:
                usb_hint = None
            if usb_hint and board_key != usb_hint:
                board_key = usb_hint

            if board_key:
                with lock:
                    cached = cache.get(fp)
                    if cached is not None:
                        cached["board_key"] = board_key
                        cached["model_text"] = info_text
                _emit(
                    f"SERIAL TRANSIENT LEARNED port={port} fp={fp!r} board={board_key!r} chars={len(info_text)}"
                )
                return services.DeviceInfo(
                    port,
                    str(getattr(item, "description", "") or "Serielles USB-Gerät"),
                    board_key,
                    info_text,
                )

            if port_present(port, fp):
                learned = entry.get("board_key")
                learned_text = str(entry.get("model_text") or "")
                _emit(
                    f"SERIAL TRANSIENT KEEP port={port} fp={fp!r} board={learned!r} "
                    "physical_present=1"
                )
                return services.DeviceInfo(
                    port,
                    str(getattr(item, "description", "") or "Serielles USB-Gerät"),
                    learned,
                    info_text or learned_text,
                )

            # Port disappeared while the helper was starting/running. Continue
            # following the same physical fingerprint rather than returning a ghost.
            _emit(f"SERIAL TRANSIENT LOST-DURING-PROBE port={port} fp={fp!r} continuing=1")
            time.sleep(0.10)

        _emit(f"SERIAL TRANSIENT GIVEUP fp={fp!r} last_port={last_port} reason=no-stable-reappearance")
        return None

    def scan_devices(*args: Any, **kwargs: Any):
        devices = base_scan(*args, **kwargs)
        learn_from_devices(devices)
        if devices:
            return devices

        entries = recent_entries()
        if not entries:
            return devices

        # Chase most recently seen physical devices first.  The normal scanner
        # already rejected them as unstable, so this path is only for brief USB
        # appearances/re-enumeration, never for Bluetooth or historical ports.
        for entry in entries[:4]:
            age = time.monotonic() - float(entry.get("last_seen", 0.0))
            if age > ttl_seconds:
                continue
            recovered = probe_reappearance(entry)
            if recovered is not None:
                return [recovered]
        return []

    services.scan_devices = scan_devices
    _emit(
        "SERIAL TRANSIENT installed ttl=12s chase=8s poll=100ms physical-fingerprint=1 "
        "reenumeration=1 ghost-drop=1"
    )
