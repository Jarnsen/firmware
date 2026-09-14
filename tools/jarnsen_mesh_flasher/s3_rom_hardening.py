from __future__ import annotations

import threading
import time
from typing import Any, Callable

_INSTALLED = False
_NATIVE_S3_DUAL_SLOT_BOARDS = frozenset({"tracker", "repeater"})
_FLASH_CONTEXT = threading.local()


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isalnum()).upper()


def _same_physical_usb(expected: Any, candidate: Any) -> bool:
    """Match a physical USB device without ever degrading to VID/PID only."""
    if expected is None or candidate is None:
        return False

    expected_serial = _norm(getattr(expected, "serial_number", ""))
    candidate_serial = _norm(getattr(candidate, "serial_number", ""))
    expected_location = _norm(getattr(expected, "location", ""))
    candidate_location = _norm(getattr(candidate, "location", ""))

    if expected_serial and expected_location:
        return (
            candidate_serial == expected_serial
            and candidate_location == expected_location
        )
    if expected_serial:
        return bool(candidate_serial) and candidate_serial == expected_serial
    if expected_location:
        return bool(candidate_location) and candidate_location == expected_location
    return False


def _identity_label(fingerprint: Any) -> str:
    serial = str(getattr(fingerprint, "serial_number", "") or "").strip()
    location = str(getattr(fingerprint, "location", "") or "").strip()
    if serial and location:
        return f"serial={serial!r} location={location!r}"
    if serial:
        return f"serial={serial!r}"
    if location:
        return f"location={location!r}"
    return "no-strong-usb-id"


def _read_fingerprint(manager: Any, port: str) -> Any:
    reader = getattr(manager, "_read_fingerprint", None)
    if callable(reader):
        value = reader(port)
        if value is not None:
            return value
    remember = getattr(manager, "remember", None)
    return remember(port) if callable(remember) else None


def prepare_s3_download_mode(
    services: Any,
    port: str,
    board_key: str,
    log: Callable[[str], None] | None = None,
) -> str:
    """Enter ESP32-S3 ROM mode and keep the exact physical Tracker/V3 pinned.

    The first destructive operation is allowed only after:
    1. a serial/location identity was captured,
    2. the transport-appropriate ESP32-S3 reset was issued,
    3. the same physical USB device was followed through re-enumeration, and
    4. a ``no-reset`` ROM readback succeeded on that exact device.
    """

    board = str(board_key or "").strip().lower()
    if board not in _NATIVE_S3_DUAL_SLOT_BOARDS:
        return str(port)

    manager = getattr(services, "device_sessions", None)
    remember = getattr(manager, "remember", None)
    waiter = getattr(services, "wait_for_device_reconnect", None)
    if manager is None or not callable(remember) or not callable(waiter):
        raise services.FlasherError(
            "S3_PHYSICAL_ID_REQUIRED: Der sichere Geräte- und Reconnect-Dienst "
            "ist nicht aktiv. Flash löschen bleibt gesperrt."
        )

    logical_port = str(port or "").strip()
    expected = remember(logical_port)
    if expected is None or not (
        _norm(getattr(expected, "serial_number", ""))
        or _norm(getattr(expected, "location", ""))
    ):
        raise services.FlasherError(
            "S3_PHYSICAL_ID_REQUIRED: Tracker/V3 hat keine eindeutige USB-Seriennummer "
            "oder physische USB-Position. Flash löschen bleibt gesperrt."
        )

    from flash_runtime import _stream_esptool

    reset_before = (
        "usb-reset" if getattr(expected, "vid", None) == 0x303A else "default-reset"
    )
    current = logical_port
    last_probe = ""
    for attempt in range(1, 3):
        if log:
            log(
                f"BOOTLOADER · ESP32-S3 USB-ROM · {board} · Versuch {attempt}/2 · "
                f"Port={current}"
            )

        try:
            result = _stream_esptool(
                services,
                current,
                [
                    "--chip",
                    "esp32s3",
                    "--before",
                    reset_before,
                    "--after",
                    "no-reset",
                    "read-flash-status",
                ],
                timeout=30,
                stage=f"ESP32-S3 USB Reset {attempt}/2",
                phase_start=0.00,
                phase_end=0.015 + 0.01 * attempt,
                log=log,
                check=False,
            )
            _emit(
                f"S3 ROM RESET board={board!r} attempt={attempt}/2 "
                f"port={current!r} before={reset_before!r} "
                f"exit={int(getattr(result, 'returncode', 1))}"
            )
        except Exception as exc:
            # USB can disappear while reset is in flight. Reconnect identity +
            # the ROM probe below are the only success criteria.
            _emit(
                f"S3 ROM RESET transient board={board!r} attempt={attempt}/2 "
                f"port={current!r} before={reset_before!r} type={type(exc).__name__} "
                f"message={str(exc)[:320]!r}"
            )

        try:
            rebound = str(
                waiter(logical_port, timeout=20, expected_board=board)
            ).strip()
        except Exception as exc:
            last_probe = f"{type(exc).__name__}: {exc}"
            if attempt >= 2:
                break
            if log:
                log(
                    "BOOTLOADER · dasselbe physische USB-Gerät noch nicht wieder da · "
                    f"{last_probe}"
                )
            time.sleep(1.0)
            continue

        actual = _read_fingerprint(manager, rebound)
        if not _same_physical_usb(expected, actual):
            raise services.FlasherError(
                "S3_PHYSICAL_ID_MISMATCH: Nach dem USB-Reset erschien nicht exakt "
                "dasselbe physische Tracker/V3-Gerät. Wechsel auf ein anderes "
                "303A:1001-Gerät wurde vor Flash löschen blockiert. "
                "Erwartet "
                f"{_identity_label(expected)}, gefunden {_identity_label(actual)}."
            )

        current = rebound
        try:
            probe = _stream_esptool(
                services,
                current,
                [
                    "--chip",
                    "esp32s3",
                    "--before",
                    "no-reset",
                    "--after",
                    "no-reset",
                    "read-flash-status",
                ],
                timeout=20,
                stage=f"ESP32-S3 ROM Probe {attempt}/2",
                phase_start=0.02,
                phase_end=0.04,
                log=log,
                check=False,
            )
            last_probe = str(getattr(probe, "stdout", "") or "")
            if int(getattr(probe, "returncode", 1)) == 0:
                if log:
                    log(
                        f"BOOTLOADER · ESP32-S3 ROM bestätigt · Port={current} · "
                        f"{_identity_label(actual)}"
                    )
                _emit(
                    f"S3 ROM READY board={board!r} port={current!r} "
                    f"reset={reset_before} forced-1200=0 physical-id-before-erase=1"
                )
                return current
        except Exception as exc:
            last_probe = f"{type(exc).__name__}: {exc}"

        if log and attempt < 2:
            log(
                "BOOTLOADER · ROM-Probe noch ohne Antwort · "
                "USB-Reset wird einmal wiederholt"
            )
        time.sleep(1.0)

    raise services.FlasherError(
        "S3_BOOTLOADER_SYNC: Der ESP32-S3-ROM-Downloadmodus konnte für das "
        "gepinnten physischen Tracker/V3-Gerät nicht bestätigt werden. "
        "Flash löschen wurde nicht gestartet.\n" + last_probe[:700]
    )


def _s3_no_reset_args(args: list[str]) -> list[str]:
    values = [str(value) for value in args]
    commands = {
        "erase-flash",
        "erase_flash",
        "write-flash",
        "write_flash",
        "run",
    }
    if not any(value in commands for value in values):
        return values
    if "--chip" in values:
        return values
    return [
        "--chip",
        "esp32s3",
        "--before",
        "no-reset",
        "--after",
        "no-reset",
        *values,
    ]


def install(services: Any) -> None:
    global _INSTALLED
    if _INSTALLED or getattr(services, "_jarnsen_s3_rom_hardening", False):
        return

    import flash_runtime

    base_stream = flash_runtime._stream_esptool
    base_flash_bundle = services.flash_bundle

    def stream_esptool(
        runtime_services: Any,
        port: str,
        args: list[str],
        **kwargs: Any,
    ):
        board = str(getattr(_FLASH_CONTEXT, "board", "") or "")
        flash_port = str(getattr(_FLASH_CONTEXT, "port", "") or "")
        effective = list(args)
        if (
            board in _NATIVE_S3_DUAL_SLOT_BOARDS
            and str(port).strip().upper() == flash_port.strip().upper()
        ):
            effective = _s3_no_reset_args(effective)
        return base_stream(runtime_services, port, effective, **kwargs)

    def flash_bundle(
        port: str,
        bundle: Any,
        log: Callable[[str], None] | None = None,
    ) -> None:
        board = str(getattr(bundle, "board_key", "") or "").strip().lower()
        profile = services.BOARD_PROFILES.get(board, {})
        strategy = str(
            profile.get("flash_strategy")
            or getattr(bundle, "flash_strategy", "")
            or "dual_slot"
        ).strip().lower()
        if board not in _NATIVE_S3_DUAL_SLOT_BOARDS or strategy != "dual_slot":
            return base_flash_bundle(port, bundle, log=log)

        # This is deliberately before base_flash_bundle: no erase/write command
        # may run until ROM mode and the exact physical USB identity are proven.
        flash_port = prepare_s3_download_mode(
            services,
            port,
            board,
            log=log,
        )
        previous_board = getattr(_FLASH_CONTEXT, "board", None)
        previous_port = getattr(_FLASH_CONTEXT, "port", None)
        _FLASH_CONTEXT.board = board
        _FLASH_CONTEXT.port = flash_port
        try:
            return base_flash_bundle(flash_port, bundle, log=log)
        finally:
            if previous_board is None:
                try:
                    delattr(_FLASH_CONTEXT, "board")
                except AttributeError:
                    pass
            else:
                _FLASH_CONTEXT.board = previous_board
            if previous_port is None:
                try:
                    delattr(_FLASH_CONTEXT, "port")
                except AttributeError:
                    pass
            else:
                _FLASH_CONTEXT.port = previous_port

    flash_runtime._stream_esptool = stream_esptool
    services.flash_bundle = flash_bundle
    services.prepare_s3_download_mode = (
        lambda port, board_key, log=None: prepare_s3_download_mode(
            services, port, board_key, log=log
        )
    )
    services._jarnsen_s3_rom_hardening = True
    _INSTALLED = True
    _emit(
        "S3 ROM HARDENING installed boards=tracker,repeater transport-aware-reset=1 "
        "usb-reset=1 default-reset=1 forced-1200=0 physical-id-before-erase=1 "
        "vidpid-only-rebind=0 "
        "no-reset-destructive-chain=1"
    )
