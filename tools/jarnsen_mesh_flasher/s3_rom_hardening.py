from __future__ import annotations

import threading
import time
from typing import Any, Callable

_INSTALLED = False
_NATIVE_S3_DUAL_SLOT_BOARDS = frozenset({"tracker", "repeater"})
_FLASH_CONTEXT = threading.local()
_TOOL_INFO_MARKER = "===JARNSEN_INFO==="
_ROM_BOOT_MARKER = "===JARNSEN_ROM_BOOT==="


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


def _matching_live_usb_ports(
    manager: Any,
    expected: Any,
    *,
    exclude: tuple[str, ...] = (),
) -> list[tuple[str, Any]]:
    """Enumerate only live ports that retain the locked strong USB identity."""
    try:
        from serial.tools import list_ports

        items = list(list_ports.comports())
    except Exception as exc:
        _emit(
            "S3 ROM ENUMERATION failed "
            f"type={type(exc).__name__} message={str(exc)[:320]!r}"
        )
        return []

    excluded = {str(value or "").strip().upper() for value in exclude}
    matches: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        port = str(getattr(item, "device", "") or "").strip()
        key = port.upper()
        if not port or key in excluded or key in seen:
            continue
        seen.add(key)
        actual = _read_fingerprint(manager, port)
        if _same_physical_usb(expected, actual):
            matches.append((port, actual))

    matches.sort(key=lambda pair: pair[0].upper())
    return matches


def _record_path(services: Any, board: str, path: str, port: str) -> None:
    services._jarnsen_s3_rom_last_path = str(path)
    services._jarnsen_s3_rom_last_board = str(board)
    services._jarnsen_s3_rom_last_port = str(port)
    _emit(f"S3 ROM PATH board={board!r} path={path!r} port={port!r}")


def _probe_rom(
    services: Any,
    port: str,
    board: str,
    *,
    log: Callable[[str], None] | None = None,
    stage: str,
    timeout: int = 12,
) -> tuple[bool, str]:
    """Probe the ESP32-S3 ROM without toggling reset/DTR/RTS."""
    from flash_runtime import _stream_esptool

    try:
        result = _stream_esptool(
            services,
            str(port),
            [
                "--chip",
                "esp32s3",
                "--before",
                "no-reset",
                "--after",
                "no-reset",
                "read-flash-status",
            ],
            timeout=timeout,
            stage=stage,
            phase_start=0.00,
            phase_end=0.025,
            log=log,
            check=False,
        )
        output = "\n".join(
            value
            for value in (
                str(getattr(result, "stdout", "") or ""),
                str(getattr(result, "stderr", "") or ""),
            )
            if value
        )
        ok = int(getattr(result, "returncode", 1)) == 0
        _emit(
            f"S3 ROM PROBE board={board!r} port={str(port)!r} stage={stage!r} "
            f"exit={int(getattr(result, 'returncode', 1))} no-reset=1"
        )
        return ok, output
    except Exception as exc:
        _emit(
            f"S3 ROM PROBE board={board!r} port={str(port)!r} stage={stage!r} "
            f"type={type(exc).__name__} message={str(exc)[:320]!r} no-reset=1"
        )
        return False, f"{type(exc).__name__}: {exc}"


def _manual_boot_required(services: Any, detail: str = "") -> BaseException:
    suffix = f" Technisches Detail: {detail[:500]}" if detail else ""
    return services.FlasherError(
        "S3_MANUAL_BOOT_REQUIRED: Die aktuell installierte Tracker-Firmware kann den "
        "sicheren JARNSEN_TOOL_ROM_BOOT-Dienst nicht bestätigen. Flash löschen wurde "
        "nicht gestartet. Tracker in den ESP32-S3-ROM-Bootmodus bringen: USER gedrückt "
        "halten -> RESET kurz drücken/loslassen -> USER loslassen. Danach den Flash "
        "erneut starten." + suffix
    )


def _prepare_tracker_rom(
    services: Any,
    logical_port: str,
    expected: Any,
    manager: Any,
    waiter: Callable[..., Any],
    log: Callable[[str], None] | None,
) -> str:
    # First and always: preserve a manually entered ROM downloader. No firmware
    # command and no reset is attempted until a no-reset ROM probe has failed.
    if log:
        log(f"BOOTLOADER · Tracker ROM zuerst passiv prüfen · Port={logical_port}")
    ready, probe_output = _probe_rom(
        services,
        logical_port,
        "tracker",
        log=log,
        stage="ESP32-S3 manueller ROM-Probe",
    )
    if ready:
        actual = _read_fingerprint(manager, logical_port)
        if not _same_physical_usb(expected, actual):
            raise services.FlasherError(
                "S3_PHYSICAL_ID_MISMATCH: Der manuell erkannte ROM-Port gehört nicht "
                "mehr zum ursprünglich gelockten Tracker. Flash löschen bleibt gesperrt. "
                f"Erwartet {_identity_label(expected)}, gefunden {_identity_label(actual)}."
            )
        if log:
            log(
                "BOOTLOADER · vorhandener manueller ESP32-S3-ROM-Modus bestätigt · "
                f"Port={logical_port} · {_identity_label(actual)}"
            )
        _record_path(services, "tracker", "manual-rom", logical_port)
        return logical_port

    # Application mode: Build 185 is the first approved reference that advertises
    # rom_boot=1 and accepts JARNSEN_TOOL_ROM_BOOT. Old/foreign firmware fails
    # closed and instructs the operator to use the one-time USER+RESET bootstrap.
    try:
        import radio_profile_node_sync as node_sync

        info = node_sync._raw_command(
            logical_port,
            "JARNSEN_TOOL_INFO",
            expected=_TOOL_INFO_MARKER,
            timeout=4.5,
        )
    except Exception as exc:
        raise _manual_boot_required(
            services,
            f"TOOL_INFO nicht verfügbar ({type(exc).__name__}: {exc})",
        ) from exc

    if "rom_boot=1" not in str(info):
        raise _manual_boot_required(
            services,
            "JARNSEN_TOOL_INFO meldet rom_boot=1 nicht",
        )

    current = _read_fingerprint(manager, logical_port)
    if not _same_physical_usb(expected, current):
        raise services.FlasherError(
            "S3_PHYSICAL_ID_MISMATCH: Vor JARNSEN_TOOL_ROM_BOOT ist nicht mehr exakt "
            "derselbe physische Tracker angeschlossen. Flash löschen bleibt gesperrt. "
            f"Erwartet {_identity_label(expected)}, gefunden {_identity_label(current)}."
        )

    if log:
        log(
            "BOOTLOADER · Build-185-ROM-Service bestätigt · "
            "JARNSEN_TOOL_ROM_BOOT wird angefordert"
        )
    try:
        response = node_sync._raw_command(
            logical_port,
            "JARNSEN_TOOL_ROM_BOOT",
            expected=_ROM_BOOT_MARKER,
            timeout=5.0,
        )
    except Exception as exc:
        raise services.FlasherError(
            "S3_ROM_SERVICE_FAILED: JARNSEN_TOOL_ROM_BOOT wurde von der bestätigten "
            f"Firmware nicht quittiert. Flash löschen bleibt gesperrt. {type(exc).__name__}: {exc}"
        ) from exc

    if "accepted=1" not in str(response) or "chip=esp32s3" not in str(response).lower():
        raise services.FlasherError(
            "S3_ROM_SERVICE_REJECTED: Die Tracker-Firmware hat den ROM-Boot-Dienst "
            f"nicht eindeutig bestätigt: {str(response)[:500]}"
        )

    # Windows may keep the former application COM alias visible while the ROM
    # USB-Serial/JTAG interface re-enumerates under another COM number. The
    # generic application reconnect helper intentionally prefers the old COM;
    # therefore it is only the first candidate. If its no-reset ROM probe fails,
    # enumerate every live serial port and try only ports carrying the exact
    # locked USB serial/location. A successful ROM probe remains the authority.
    time.sleep(0.35)
    last_probe = probe_output
    for attempt in range(1, 6):
        rebound = ""
        try:
            rebound = str(
                waiter(logical_port, timeout=6, expected_board="tracker")
            ).strip()
        except Exception as exc:
            last_probe = f"{type(exc).__name__}: {exc}"

        if rebound:
            actual = _read_fingerprint(manager, rebound)
            if not _same_physical_usb(expected, actual):
                raise services.FlasherError(
                    "S3_PHYSICAL_ID_MISMATCH: Nach JARNSEN_TOOL_ROM_BOOT erschien nicht "
                    "exakt derselbe physische Tracker. Ein Wechsel auf ein anderes USB-Gerät "
                    "wurde vor Flash löschen blockiert. "
                    f"Erwartet {_identity_label(expected)}, gefunden {_identity_label(actual)}."
                )

            ready, last_probe = _probe_rom(
                services,
                rebound,
                "tracker",
                log=log,
                stage=f"ESP32-S3 Build-185 ROM-Probe {attempt}/5",
                timeout=8,
            )
            if ready:
                if log:
                    log(
                        "BOOTLOADER · JARNSEN_TOOL_ROM_BOOT erfolgreich · ESP32-S3-ROM bestätigt · "
                        f"Port={rebound} · {_identity_label(actual)}"
                    )
                _record_path(services, "tracker", "firmware-service", rebound)
                return rebound

        alternate_ports = _matching_live_usb_ports(
            manager,
            expected,
            exclude=(rebound, logical_port),
        )
        if alternate_ports and log:
            names = ", ".join(port for port, _fingerprint in alternate_ports)
            log(
                "BOOTLOADER · Windows-ROM-Neuanmeldung erkannt · "
                f"starker USB-ID-Treffer auf {names}"
            )
        for alternate_port, alternate_fingerprint in alternate_ports:
            ready, last_probe = _probe_rom(
                services,
                alternate_port,
                "tracker",
                log=log,
                stage=(
                    f"ESP32-S3 Build-185 ROM-Probe alternativ {attempt}/5 · "
                    f"{alternate_port}"
                ),
                timeout=8,
            )
            if ready:
                if log:
                    log(
                        "BOOTLOADER · JARNSEN_TOOL_ROM_BOOT erfolgreich · ESP32-S3-ROM bestätigt · "
                        f"Port={alternate_port} · {_identity_label(alternate_fingerprint)}"
                    )
                _record_path(
                    services,
                    "tracker",
                    "firmware-service",
                    alternate_port,
                )
                return alternate_port

        if attempt < 5:
            time.sleep(0.6)

    raise services.FlasherError(
        "S3_BOOTLOADER_SYNC: JARNSEN_TOOL_ROM_BOOT wurde akzeptiert, aber der "
        "ESP32-S3-ROM-Downloader konnte auf demselben physischen Tracker nicht "
        "bestätigt werden. Flash löschen wurde nicht gestartet. " + last_probe[:700]
    )


def _prepare_bridge_rom(
    services: Any,
    logical_port: str,
    board: str,
    expected: Any,
    manager: Any,
    waiter: Callable[..., Any],
    log: Callable[[str], None] | None,
) -> str:
    """Keep the proven bridge/default-reset path for Heltec V3."""
    from flash_runtime import _stream_esptool

    current = logical_port
    last_probe = ""
    for attempt in range(1, 3):
        if log:
            log(
                f"BOOTLOADER · ESP32-S3 Bridge-ROM · {board} · Versuch {attempt}/2 · "
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
                    "default-reset",
                    "--after",
                    "no-reset",
                    "read-flash-status",
                ],
                timeout=30,
                stage=f"ESP32-S3 Bridge Reset {attempt}/2",
                phase_start=0.00,
                phase_end=0.015 + 0.01 * attempt,
                log=log,
                check=False,
            )
            _emit(
                f"S3 ROM RESET board={board!r} attempt={attempt}/2 port={current!r} "
                f"before='default-reset' exit={int(getattr(result, 'returncode', 1))}"
            )
        except Exception as exc:
            last_probe = f"{type(exc).__name__}: {exc}"

        try:
            rebound = str(
                waiter(logical_port, timeout=20, expected_board=board)
            ).strip()
        except Exception as exc:
            last_probe = f"{type(exc).__name__}: {exc}"
            if attempt < 2:
                time.sleep(1.0)
                continue
            break

        actual = _read_fingerprint(manager, rebound)
        if not _same_physical_usb(expected, actual):
            raise services.FlasherError(
                "S3_PHYSICAL_ID_MISMATCH: Nach dem Bridge-Reset erschien nicht exakt "
                "dasselbe physische Tracker/V3-Gerät. Wechsel auf ein anderes Gerät "
                "wurde vor Flash löschen blockiert. "
                f"Erwartet {_identity_label(expected)}, gefunden {_identity_label(actual)}."
            )

        current = rebound
        ready, last_probe = _probe_rom(
            services,
            current,
            board,
            log=log,
            stage=f"ESP32-S3 Bridge ROM-Probe {attempt}/2",
        )
        if ready:
            if log:
                log(
                    f"BOOTLOADER · ESP32-S3 ROM bestätigt · Port={current} · "
                    f"{_identity_label(actual)}"
                )
            _record_path(services, board, "bridge-reset", current)
            return current
        time.sleep(1.0)

    raise services.FlasherError(
        "S3_BOOTLOADER_SYNC: Der ESP32-S3-ROM-Downloadmodus konnte für das "
        "gepinnten physische Tracker/V3-Gerät nicht bestätigt werden. "
        "Flash löschen wurde nicht gestartet. " + last_probe[:700]
    )


def prepare_s3_download_mode(
    services: Any,
    port: str,
    board_key: str,
    log: Callable[[str], None] | None = None,
) -> str:
    """Enter ESP32-S3 ROM mode while pinning the exact physical Tracker/V3."""
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

    native_usb = getattr(expected, "vid", None) == 0x303A
    if board == "tracker" and native_usb:
        return _prepare_tracker_rom(
            services,
            logical_port,
            expected,
            manager,
            waiter,
            log,
        )
    return _prepare_bridge_rom(
        services,
        logical_port,
        board,
        expected,
        manager,
        waiter,
        log,
    )


def _s3_flash_args(args: list[str], board: str) -> list[str]:
    """Preserve ROM for erase/write, then leave download mode deliberately."""
    values = [str(value) for value in args]
    destructive = {"erase-flash", "erase_flash", "write-flash", "write_flash"}
    has_destructive = any(value in destructive for value in values)
    has_run = "run" in values
    if not has_destructive and not has_run:
        return values
    if "--chip" in values:
        return values

    after = "no-reset"
    if has_run:
        # Native USB-Serial/JTAG can remain latched in download mode after a
        # manual USER+RESET bootstrap. A watchdog reset is a full system reset
        # and re-samples the strapping pins. Bridge boards use hard reset.
        after = "watchdog-reset" if board == "tracker" else "hard-reset"

    return [
        "--chip",
        "esp32s3",
        "--before",
        "no-reset",
        "--after",
        after,
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
            effective = _s3_flash_args(effective, board)
        return base_stream(runtime_services, port, effective, **kwargs)

    def flash_bundle(
        port: str,
        bundle: Any,
        log: Callable[[str], None] | None = None,
    ) -> None:
        board = str(getattr(bundle, "board_key", "") or "").strip().lower()
        profile = services.BOARD_PROFILES.get(board, {})
        strategy = (
            str(
                profile.get("flash_strategy")
                or getattr(bundle, "flash_strategy", "")
                or "dual_slot"
            )
            .strip()
            .lower()
        )
        if board not in _NATIVE_S3_DUAL_SLOT_BOARDS or strategy != "dual_slot":
            return base_flash_bundle(port, bundle, log=log)

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
    services.prepare_s3_download_mode = lambda port, board_key, log=None: (
        prepare_s3_download_mode(services, port, board_key, log=log)
    )
    services._jarnsen_s3_rom_hardening = True
    _INSTALLED = True
    _emit(
        "S3 ROM HARDENING installed boards=tracker,repeater transport-aware-reset=1 "
        "manual-rom-first=1 firmware-rom-service=1 manual-boot-required=1 "
        "physical-id-before-erase=1 vidpid-only-rebind=0 forced-1200=0 "
        "rom-port-scan=1 no-reset-destructive-chain=1 tracker-watchdog-start=1 "
        "bridge-hard-reset-start=1"
    )
