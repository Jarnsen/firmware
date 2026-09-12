from __future__ import annotations

import time
from typing import Any


_INSTALLED = False


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def prepare_supreme_download_mode(services: Any, port: str, log: Any) -> str:
    """Enter ESP32-S3 ROM download mode without mixing reset strategies.

    ESP32-S3 native USB Serial/JTAG uses esptool's dedicated ``usb-reset``
    strategy.  A 1200-baud data rate is not part of that reset contract and can
    make Windows tear down the active COM handle while esptool is still trying
    to configure it.  We therefore trigger USB reset at esptool's normal ROM
    transport settings, follow the *same physical USB device* through
    re-enumeration, and confirm download mode with a no-reset probe.
    """
    from flash_runtime import _stream_esptool

    current = str(port or "").strip()

    def live_port(value: str) -> str | None:
        checker = getattr(services, "live_serial_port", None)
        if callable(checker):
            try:
                result = checker(value)
                return str(result).strip() if result else None
            except Exception:
                return None
        return str(value or "").strip() or None

    initial = live_port(current)
    if not initial:
        raise services.FlasherError(
            "SUPREME_PORT_MISSING: Der gewählte Supreme-COM-Port ist nicht aktiv."
        )
    current = initial

    manager = getattr(services, "device_sessions", None)
    remember = getattr(manager, "remember", None)
    if callable(remember):
        remember(current)

    last_probe = ""
    for attempt in range(1, 3):
        if log:
            log(
                f"BOOTLOADER · Supreme USB-Serial/JTAG Reset · Versuch {attempt}/2 · "
                f"Port={current}"
            )

        # A successful usb-reset may intentionally disconnect the COM port before
        # the command can finish cleanly.  Return code is therefore diagnostic,
        # not the readiness verdict.  Readiness is decided only by the later
        # no-reset ROM probe on the re-enumerated physical device.
        try:
            reset_result = _stream_esptool(
                services,
                current,
                [
                    "--chip", "esp32s3",
                    "--before", "usb-reset",
                    "--after", "no-reset",
                    "read-flash-status",
                ],
                timeout=30,
                stage=f"Supreme USB Reset {attempt}/2",
                phase_start=0.01,
                phase_end=0.03 + 0.02 * attempt,
                log=log,
                check=False,
            )
            _emit(
                f"SUPREME USB RESET attempt={attempt}/2 port={current!r} "
                f"exit={int(getattr(reset_result, 'returncode', 1))}"
            )
        except Exception as exc:
            # A disappearing native USB port is expected during reset.  The
            # physical-identity reconnect gate below decides whether it is safe
            # to continue; never rebind based on VID/PID alone.
            _emit(
                f"SUPREME USB RESET transient attempt={attempt}/2 port={current!r} "
                f"type={type(exc).__name__} message={str(exc)[:300]!r}"
            )

        waiter = getattr(services, "wait_for_device_reconnect", None)
        if callable(waiter):
            try:
                current = str(
                    waiter(current, timeout=20, expected_board="tbeam_supreme")
                ).strip()
            except Exception as exc:
                if attempt >= 2:
                    raise services.FlasherError(
                        "SUPREME_BOOTLOADER_SYNC: Nach dem USB-Reset konnte dasselbe "
                        "physische Supreme-Gerät nicht eindeutig wiedergefunden werden.\n"
                        + str(exc)
                    ) from exc
                if log:
                    log(
                        "BOOTLOADER · USB-Neuanmeldung noch nicht eindeutig · "
                        f"{type(exc).__name__}: {exc}"
                    )
                time.sleep(1.0)
                continue
        else:
            resolver = getattr(services, "resolve_live_port", None)
            if callable(resolver):
                current = str(resolver(current) or current).strip()

        confirmed = live_port(current)
        if not confirmed:
            if attempt >= 2:
                raise services.FlasherError(
                    "SUPREME_BOOTLOADER_SYNC: Nach der USB-Neuanmeldung ist kein "
                    "aktiver Port des gepinnten Supreme vorhanden."
                )
            time.sleep(1.0)
            continue
        current = confirmed

        try:
            probe = _stream_esptool(
                services,
                current,
                [
                    "--chip", "esp32s3",
                    "--before", "no-reset",
                    "--after", "no-reset",
                    "read-flash-status",
                ],
                timeout=20,
                stage=f"Supreme Bootloader Probe {attempt}/2",
                phase_start=0.05,
                phase_end=0.07,
                log=log,
                check=False,
            )
            last_probe = str(getattr(probe, "stdout", "") or "")
            if int(getattr(probe, "returncode", 1)) == 0:
                if log:
                    log(f"BOOTLOADER · Downloadmodus bestätigt · Flash-Port={current}")
                _emit(
                    f"SUPREME BOOTLOADER READY port={current!r} attempt={attempt}/2 "
                    "reset=usb-reset forced-1200=0 physical-id-gate=1"
                )
                return current
        except Exception as exc:
            last_probe = f"{type(exc).__name__}: {exc}"

        if log and attempt < 2:
            log("BOOTLOADER · ROM-Probe noch ohne Antwort · USB-Reset wird einmal wiederholt")
        time.sleep(1.0)

    raise services.FlasherError(
        "SUPREME_BOOTLOADER_SYNC: Der ESP32-S3 Downloadmodus konnte nach zwei "
        "USB-Reset-/Readback-Versuchen nicht bestätigt werden.\n"
        + last_probe[:700]
    )


def install(services: Any) -> None:
    global _INSTALLED
    if _INSTALLED or getattr(services, "_jarnsen_supreme_bootloader_hardening", False):
        return

    import unified_service_v2

    unified_service_v2.prepare_supreme_download_mode = (
        lambda runtime_services, port, log: prepare_supreme_download_mode(
            runtime_services, port, log
        )
    )

    # Install after the bootloader-entry override so every factory/update path
    # writes and hash-verifies first, then performs the disconnecting native-USB
    # watchdog reset as a separate non-flash phase.
    from postflash_hardening import install as install_postflash_hardening
    install_postflash_hardening(services)

    services._jarnsen_supreme_bootloader_hardening = True
    _INSTALLED = True
    _emit(
        "SUPREME BOOTLOADER HARDENING installed usb-reset=1 forced-1200=0 "
        "post-reset-rom-probe=1 physical-id-reconnect=1 postflash-ready-gate=1"
    )
