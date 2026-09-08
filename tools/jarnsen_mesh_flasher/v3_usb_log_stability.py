from __future__ import annotations

import threading
import time
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from tkinter import messagebox
from typing import Any

import serial

import usb_log_download as usb_base


_INSTALLED = False


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _download_v3_usb_log(
    port: str,
    destination: Path,
    *,
    progress=None,
    log=None,
    timeout: float = 180.0,
    start_timeout: float = 75.0,
    request_interval: float = 2.5,
) -> Path:
    """Receive the V3 diagnostic log with a retrying raw-service handshake.

    Heltec V3 uses a CP210x bridge which can keep COM visible while the ESP32-S3
    behind it is rebooting. Opening the serial port can also happen before the raw
    service loop is ready. Therefore a one-shot JARNSEN_TOOL_FULL request is not
    reliable on V3. Retry only until the BEGIN marker is seen, then switch to the
    normal streaming parser without sending any further commands.
    """
    destination.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    last_data = started
    buffer = bytearray()
    capture = bytearray()
    found_begin = False
    expected: int | None = None
    payload_start: int | None = None
    last_report = 0.0
    request_count = 0
    next_request = started + 1.0

    def report(fraction: float, text: str) -> None:
        if progress is not None:
            try:
                progress(max(0.0, min(1.0, float(fraction))), text)
            except Exception:
                pass
        if log is not None:
            try:
                log(text)
            except Exception:
                pass

    report(0.02, f"USB-Log · V3 COM-Port öffnen · {port}")
    _emit(
        f"V3 USB LOG SERIAL OPEN port={port} baud=115200 "
        f"start_timeout={start_timeout:.0f}s retry={request_interval:.1f}s exclusive=1"
    )

    with serial.Serial(port=port, baudrate=115200, timeout=0.12, write_timeout=2.0) as ser:
        try:
            ser.reset_input_buffer()
        except Exception:
            pass

        while True:
            now = time.monotonic()
            elapsed = now - started
            if elapsed >= timeout:
                raise TimeoutError(
                    f"V3 USB-Logdownload auf {port} hat nach {int(timeout)} Sekunden das Zeitlimit erreicht."
                )

            # Enforce the handshake deadline independently of incoming console/debug
            # noise. Build 223 only checked this in the no-data branch, so a noisy V3
            # could keep the loop alive indefinitely without ever sending BEGIN.
            if not found_begin and elapsed >= start_timeout:
                raise TimeoutError(
                    f"Heltec V3 hat nach {int(start_timeout)} Sekunden und {request_count} "
                    "Service-Anfragen keinen JARNSEN-Diagnose-Startmarker gesendet."
                )

            if not found_begin and now >= next_request:
                request_count += 1
                try:
                    ser.write(usb_base.COMMAND)
                    ser.flush()
                    _emit(
                        f"V3 USB LOG COMMAND SENT port={port} attempt={request_count} "
                        f"elapsed={elapsed:.1f}s bytes={len(usb_base.COMMAND)}"
                    )
                    report(
                        0.06,
                        f"USB-Log · V3-Service anfordern · Versuch {request_count}",
                    )
                except (serial.SerialException, OSError) as exc:
                    _emit(
                        f"V3 USB LOG COMMAND RETRY port={port} attempt={request_count} "
                        f"type={type(exc).__name__} message={str(exc)[:240]!r}"
                    )
                next_request = now + max(1.0, float(request_interval))

            try:
                chunk = ser.read(4096)
            except (serial.SerialException, OSError) as exc:
                if not found_begin and elapsed < start_timeout:
                    _emit(
                        f"V3 USB LOG READ RETRY port={port} attempt={request_count} "
                        f"type={type(exc).__name__} message={str(exc)[:240]!r}"
                    )
                    time.sleep(0.25)
                    continue
                raise

            if chunk:
                last_data = now
                if not found_begin:
                    buffer.extend(chunk)
                    idx = buffer.find(usb_base.BEGIN)
                    if idx >= 0:
                        found_begin = True
                        capture.extend(buffer[idx:])
                        buffer.clear()
                        report(0.10, f"USB-Log · V3-Startmarker empfangen · Versuch {request_count}")
                        _emit(
                            f"V3 USB LOG BEGIN port={port} attempt={request_count} elapsed={elapsed:.2f}s"
                        )
                    elif len(buffer) > 65536:
                        del buffer[:-8192]
                else:
                    capture.extend(chunk)

                if found_begin:
                    if expected is None:
                        expected = usb_base._expected_bytes(bytes(capture))
                        payload_start = usb_base._payload_offset(bytes(capture))
                        if expected is not None:
                            report(0.12, f"USB-Log · {expected / 1024.0:.1f} KiB Nutzdaten angekündigt")
                            _emit(f"V3 USB LOG SIZE port={port} payload_bytes={expected}")

                    end_idx = capture.find(usb_base.END)
                    if end_idx >= 0:
                        end_pos = end_idx + len(usb_base.END)
                        while end_pos < len(capture) and capture[end_pos] in (10, 13):
                            end_pos += 1
                        completed = bytes(capture[:end_pos])
                        node_id = usb_base._header_value(completed, b"node_id")
                        long_name = usb_base._header_value(completed, b"long_name")
                        device = usb_base._header_value(completed, b"device") or "HELTEC_V3"
                        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                        stem = usb_base._safe_filename(long_name or node_id or port)
                        target = destination / f"{stem}-{usb_base._safe_filename(port)}-{stamp}.log"
                        target.write_bytes(completed)
                        payload_sent = 0
                        if payload_start is not None:
                            payload_sent = max(0, end_idx - payload_start)
                        report(1.0, f"USB-Log · Fertig · {target.name}")
                        _emit(
                            f"V3 USB LOG COMPLETE port={port} device={device!r} node={node_id!r} "
                            f"payload_expected={expected!r} payload_observed={payload_sent} "
                            f"file_bytes={len(completed)} attempts={request_count} "
                            f"path={str(target)!r} duration={elapsed:.2f}s"
                        )
                        return target

                    if expected and payload_start is not None:
                        payload_received = max(0, len(capture) - payload_start)
                        fraction = min(
                            0.97,
                            0.12 + 0.83 * min(1.0, payload_received / max(1, expected)),
                        )
                        if now - last_report >= 0.35:
                            pct = min(100.0, payload_received * 100.0 / max(1, expected))
                            report(
                                fraction,
                                f"USB-Log · {pct:.1f}% · {payload_received / 1024.0:.1f}/{expected / 1024.0:.1f} KiB",
                            )
                            last_report = now
            else:
                idle = now - last_data
                if found_begin and idle >= 20.0:
                    raise TimeoutError(
                        f"V3 USB-Logübertragung auf {port} ist seit {idle:.0f} Sekunden ohne Daten."
                    )
                if now - last_report >= 2.0:
                    if found_begin:
                        report(0.12, f"USB-Log · Warte auf weitere V3-Daten · {elapsed:.0f}s")
                    else:
                        report(
                            0.08,
                            f"USB-Log · V3-Service noch nicht bereit · Versuch {request_count} · {elapsed:.0f}s",
                        )
                    last_report = now


def install(services: Any) -> None:
    """Replace only the Heltec-V3 USB-log action with an exclusive raw handshake."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    import native_actions
    import reference_dashboard

    base_start_usb_log = native_actions.start_usb_log

    def start_usb_log(app: Any, runtime_services: Any) -> None:
        board_key = app._selected_board_key() if hasattr(app, "_selected_board_key") else None
        if board_key != "repeater":
            return base_start_usb_log(app, runtime_services)
        if getattr(app, "busy", False):
            return

        device = app._selected_device() if hasattr(app, "_selected_device") else None
        if device is None:
            messagebox.showwarning("Kein Gerät", "Bitte zuerst ein USB-Gerät auswählen.", parent=app)
            return

        # Mark the raw V3 service before the worker starts. Existing firmware-status
        # workers may finish their current locked probe, but no serial operation can
        # overlap once this worker acquires the same per-port RLock.
        app._jarnsen_v3_usb_log_active = True
        app._set_busy(True)

        def worker() -> None:
            try:
                label = runtime_services.BOARD_PROFILES["repeater"]["label"]
                app._append_log(
                    f"USB-LOG START · Port={device.port} · Board={label} · "
                    "V3-Raw-Handshake=exclusive"
                )
                app._set_progress(0.02, "USB-Log · V3 COM exklusiv reservieren")

                guard_factory = getattr(runtime_services, "jarnsen_serial_guard", None)
                guard = guard_factory(device.port) if callable(guard_factory) else nullcontext()

                # Hold one exclusive per-port lock across reboot, reconnect and the
                # complete raw transfer. services.meshtastic uses the same RLock and
                # is re-entrant in this worker, so firmware-status probes cannot slip
                # between reboot and JARNSEN_TOOL_FULL anymore.
                with guard:
                    _emit(f"V3 USB LOG EXCLUSIVE LOCK port={device.port} acquired=1")
                    app._set_progress(0.04, "USB-Log · V3 exklusiver COM-Zugriff")

                    try:
                        runtime_services.reboot_node(device.port)
                    except Exception as exc:
                        app._append_log(
                            f"USB-LOG · V3-Reboot meldet {type(exc).__name__}: {exc} · "
                            "Raw-Handshake übernimmt die Bereitschaftsprüfung"
                        )

                    app._set_progress(0.07, "USB-Log · V3-Servicebereitschaft abwarten")
                    try:
                        runtime_services.wait_for_serial(device.port, timeout=90)
                    except Exception as exc:
                        app._append_log(
                            f"USB-LOG · COM-Wartephase meldet {type(exc).__name__}: {exc} · "
                            "Raw-Handshake wird trotzdem versucht"
                        )
                    time.sleep(1.0)

                    output_dir = Path(runtime_services.PATHS.logs) / "NODE-LOGS"

                    def progress(value: float, detail: str) -> None:
                        app._set_progress(0.10 + 0.88 * max(0.0, min(1.0, value)), detail)

                    target = _download_v3_usb_log(
                        device.port,
                        output_dir,
                        progress=progress,
                        log=app._append_log,
                        timeout=180.0,
                        start_timeout=75.0,
                        request_interval=2.5,
                    )

                _emit(f"V3 USB LOG EXCLUSIVE LOCK port={device.port} released=1")
                app._set_progress(1.0, f"USB-Log gespeichert · {target.name}")
                app._append_log(f"USB-LOG ENDE · V3 ERFOLG · {target}")
                app.after(
                    0,
                    messagebox.showinfo,
                    "Node-Log gespeichert",
                    f"{label}\n\n{target}",
                )
            except Exception as exc:
                app._append_log(f"USB-LOG V3 FEHLER · {type(exc).__name__}: {exc}")
                try:
                    app._show_error(exc)
                except Exception:
                    app.after(0, messagebox.showerror, "USB-Logdownload fehlgeschlagen", str(exc))
            finally:
                app._jarnsen_v3_usb_log_active = False
                app._set_busy(False)
                try:
                    refresh = getattr(app, "refresh_firmware_status", None)
                    if callable(refresh):
                        app.after(350, refresh)
                except Exception:
                    pass

        threading.Thread(
            target=worker,
            name="jarnsen-v3-usb-log",
            daemon=True,
        ).start()

    native_actions.start_usb_log = start_usb_log
    reference_dashboard.start_usb_log = start_usb_log
    services._jarnsen_v3_usb_log_stability = True
    _emit(
        "V3 USB LOG STABILITY installed retry-command=2.5s start-timeout=75s "
        "raw-only=1 exclusive-port-lock=1 hard-handshake-timeout=1 other-boards-unchanged=1"
    )
