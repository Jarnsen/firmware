from __future__ import annotations

import re
import threading
import time
from typing import Any

import firmware_status_ui
import radio_profile_node_sync as node_sync
import radio_profiles
import serial

# A serial port can reappear several seconds before the ESP32 application and
# JARNSEN service console are actually ready. The real Tracker V1.1 log showed
# the first command being sent while the boot screen was still starting.
PROBE_TIMEOUT = 7.0
PROBE_ATTEMPTS = 1
IDENTITY_TIMEOUT = 7.0
RESEND_INTERVAL = 1.7
_UNSUPPORTED_PORTS: set[str] = set()
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _port_key(port: str) -> str:
    return str(port or "").strip().upper()


def _service_ready_hint(text: str) -> bool:
    clean = str(text or "").lower()
    return (
        "done with boot screen" in clean
        or "nodeinfo" in clean
        or "current rtc quality" in clean
        or "gps time set" in clean
    )


def _extract_service_marker(
    text: str,
    marker: str,
    *,
    include_unterminated: bool = False,
) -> str | None:
    """Extract one service line without accepting a fragmented final chunk.

    Normal reads only accept newline-terminated lines. At timeout/final-buffer
    handling we may also accept the last unterminated line because the ESP32 USB
    CDC stream can omit/delay its trailing newline. ANSI colour prefixes are
    removed and any boot-log prefix before the marker is ignored.
    """
    if not marker:
        return None
    clean = _ANSI_ESCAPE_RE.sub("", str(text or "")).replace("\r", "\n")
    lines = clean.split("\n")
    final_index = len(lines) - 1
    for index_line, raw_line in enumerate(lines):
        if index_line == final_index and raw_line and not include_unterminated:
            continue
        marker_index = raw_line.find(marker)
        if marker_index < 0:
            continue
        line = raw_line[marker_index:].strip()
        if line:
            return line
    return None


def _stable_raw_command(
    port: str, command: str, *, expected: str, timeout: float = 10.0
) -> str:
    """Send a JARNSEN raw command reliably across USB/boot timing races."""
    effective_timeout = max(float(timeout), 6.5)
    deadline = time.monotonic() + effective_timeout
    buffer = bytearray()
    payload = (command.rstrip() + "\n").encode("ascii", errors="strict")
    attempts = 0
    last_send = 0.0
    next_send = time.monotonic() + 0.30
    ready_resend_used = False

    with serial.Serial(
        port=port, baudrate=115200, timeout=0.12, write_timeout=2.0
    ) as ser:
        try:
            ser.reset_input_buffer()
        except Exception:
            pass

        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_send:
                ser.write(payload)
                ser.flush()
                attempts += 1
                last_send = now
                next_send = now + RESEND_INTERVAL
                _emit(
                    f"RADIO NODE SYNC command={command!r} port={port} attempt={attempts} "
                    f"stable-usb=1"
                )

            chunk = ser.read(512)
            if chunk:
                buffer.extend(chunk)
                text = buffer.decode("utf-8", errors="replace")

                error_line = _extract_service_marker(text, node_sync.RADIO_ERROR_MARKER)
                if error_line is not None:
                    raise RuntimeError(error_line)

                response_line = _extract_service_marker(text, expected)
                if response_line is not None:
                    _emit(
                        f"RADIO NODE SYNC response={response_line!r} port={port} attempts={attempts} "
                        f"stable-usb=1 terminated=1 ansi-safe=1"
                    )
                    return response_line

                if (
                    not ready_resend_used
                    and _service_ready_hint(text)
                    and time.monotonic() - last_send >= 0.20
                ):
                    next_send = min(next_send, time.monotonic() + 0.05)
                    ready_resend_used = True
            else:
                time.sleep(0.03)

    seen = buffer.decode("utf-8", errors="replace")
    error_line = _extract_service_marker(
        seen,
        node_sync.RADIO_ERROR_MARKER,
        include_unterminated=True,
    )
    if error_line is not None:
        raise RuntimeError(error_line)
    response_line = _extract_service_marker(
        seen,
        expected,
        include_unterminated=True,
    )
    if response_line is not None:
        _emit(
            f"RADIO NODE SYNC response={response_line!r} port={port} attempts={attempts} "
            f"stable-usb=1 final-buffer=1 unterminated-safe=1 ansi-safe=1"
        )
        return response_line

    tail = seen[-900:]
    raise TimeoutError(
        f"Keine Antwort auf {command!r} von {port} nach {attempts} Versuch(en). "
        f"Die installierte Firmware unterstützt den JARNSEN-USB-Dienst möglicherweise noch nicht. "
        f"Empfangen: {tail!r}"
    )


def _stable_identity_query(port: str, timeout: float = 1.8):
    """Read JARNSEN identity without misclassifying a booting node as VANILLA."""
    effective_timeout = max(float(timeout), IDENTITY_TIMEOUT)
    deadline = time.monotonic() + effective_timeout
    buffer = bytearray()
    attempts = 0
    last_send = 0.0
    next_send = time.monotonic() + 0.30
    ready_resend_used = False

    try:
        with serial.Serial(
            port=port, baudrate=115200, timeout=0.10, write_timeout=1.5
        ) as handle:
            try:
                handle.reset_input_buffer()
            except Exception:
                pass

            while time.monotonic() < deadline:
                now = time.monotonic()
                if now >= next_send:
                    handle.write(firmware_status_ui.INFO_COMMAND)
                    handle.flush()
                    attempts += 1
                    last_send = now
                    next_send = now + RESEND_INTERVAL
                    _emit(
                        f"FIRMWARE IDENTITY USB SEND port={port} attempt={attempts} stable-usb=1"
                    )

                chunk = handle.read(512)
                if chunk:
                    buffer.extend(chunk)
                    text = buffer.decode("utf-8", errors="replace")
                    for line in text.replace("\r", "\n").split("\n")[:-1]:
                        identity = firmware_status_ui._parse_service_line(line)
                        if identity is not None:
                            _emit(
                                f"FIRMWARE IDENTITY USB port={port} product={identity.product!r} "
                                f"version={identity.version!r} build={identity.build!r} "
                                f"hardware={identity.hardware!r} sha={identity.sha!r} "
                                f"attempts={attempts} stable-usb=1"
                            )
                            return identity

                    if (
                        not ready_resend_used
                        and _service_ready_hint(text)
                        and time.monotonic() - last_send >= 0.20
                    ):
                        next_send = min(next_send, time.monotonic() + 0.05)
                        ready_resend_used = True
                else:
                    time.sleep(0.03)
    except Exception as exc:
        _emit(
            f"FIRMWARE IDENTITY USB SKIP port={port} type={type(exc).__name__} "
            f"message={exc} stable-usb=1"
        )
        return None

    _emit(
        f"FIRMWARE IDENTITY USB NO-RESPONSE port={port} timeout={effective_timeout:.1f}s "
        f"bytes={len(buffer)} attempts={attempts} stable-usb=1"
    )
    return None


def _compat_active_profile(port: str, services: Any) -> str:
    """Probe the optional three-slot service without breaking VANILLA/legacy nodes."""
    key = _port_key(port)
    node_sync._reboot_to_raw(port, services)
    last_error: Exception | None = None

    for attempt in range(1, PROBE_ATTEMPTS + 1):
        try:
            line = node_sync._raw_command(
                port,
                "JARNSEN_TOOL_RADIO_INFO",
                expected=node_sync.RADIO_INFO_MARKER,
                timeout=PROBE_TIMEOUT,
            )
            match = node_sync.ACTIVE_RE.search(line)
            if not match:
                raise RuntimeError(
                    f"Aktives Funkprofil konnte nicht aus der Firmware-Antwort gelesen werden: {line}"
                )
            active = match.group(1).lower()
            _UNSUPPORTED_PORTS.discard(key)
            _emit(
                "RADIO NODE SYNC compatibility-probe "
                f"port={port} slots-supported=1 active={active} attempt={attempt}"
            )
            return active
        except (TimeoutError, RuntimeError) as exc:
            last_error = exc
            _emit(
                "RADIO NODE SYNC compatibility-probe retry "
                f"port={port} slots-supported=unknown attempt={attempt}/{PROBE_ATTEMPTS} "
                f"type={type(exc).__name__}"
            )
            if attempt < PROBE_ATTEMPTS:
                try:
                    services.wait_for_serial(port, timeout=15)
                except Exception:
                    pass
                time.sleep(0.35)

    _UNSUPPORTED_PORTS.add(key)
    _emit(
        "RADIO NODE SYNC compatibility-fallback "
        f"port={port} slots-supported=0 fallback=standard-only no-fatal=1 "
        f"type={type(last_error).__name__ if last_error is not None else 'unknown'}"
    )
    return radio_profiles.PROFILE_STANDARD


def _install_dashboard_identity_refresh(services: Any) -> None:
    """Never let a selected PC firmware suppress installed-node identity probing."""
    import reference_dashboard

    if getattr(reference_dashboard, "_jarnsen_installed_identity_refresh", False):
        return
    reference_dashboard._jarnsen_installed_identity_refresh = True
    base_build_dashboard = reference_dashboard._build_dashboard

    def build_dashboard(app: Any, runtime_services: Any) -> None:
        base_build_dashboard(app, runtime_services)
        if getattr(app, "_jarnsen_installed_identity_refresh_ready", False):
            return
        app._jarnsen_installed_identity_refresh_ready = True
        identity_generation = {"value": 0}
        base_refresh = getattr(app, "refresh_firmware_status", None)

        def refresh_installed_identity() -> None:
            identity_generation["value"] += 1
            token = identity_generation["value"]
            device = app._selected_device()
            if device is None:
                return
            port = str(getattr(device, "port", "") or "")
            if not port:
                return

            fallback = firmware_status_ui.parse_installed_firmware(
                getattr(device, "model_text", "")
            )
            # The normal Meshtastic protobuf currently reports firmwareEdition
            # VANILLA even for the custom build. Do not present that fallback as
            # authoritative while the JARNSEN service identity is being queried.
            if not fallback.is_jarnsen:
                app.installed_firmware_var.set("Installiert: wird exakt geprüft …")

            def worker() -> None:
                exact = _stable_identity_query(port)
                identity = exact or fallback

                def update() -> None:
                    if token != identity_generation["value"]:
                        return
                    current = app._selected_device()
                    if current is None or _port_key(
                        getattr(current, "port", "")
                    ) != _port_key(port):
                        return
                    app.installed_firmware_var.set(
                        f"Installiert: {firmware_status_ui._installed_display(identity)}"
                    )
                    if exact is not None:
                        try:
                            app._append_log(
                                "FIRMWARE IDENTITY EXACT · "
                                f"Port={port} · {firmware_status_ui._installed_display(exact)} · "
                                "PC-Datei blockiert Erkennung nicht"
                            )
                        except Exception:
                            pass

                try:
                    app.after(0, update)
                except Exception:
                    pass

            threading.Thread(
                target=worker,
                name="jarnsen-installed-identity",
                daemon=True,
            ).start()

        if callable(base_refresh):

            def combined_refresh(force: bool = False) -> None:
                base_refresh(force)
                refresh_installed_identity()

            app.refresh_firmware_status = combined_refresh

        def queue_identity(*_args: Any) -> None:
            try:
                app.after(520, refresh_installed_identity)
            except Exception:
                pass

        try:
            app.device_var.trace_add("write", queue_identity)
            app.board_var.trace_add("write", queue_identity)
            app.after(620, refresh_installed_identity)
        except Exception:
            pass

        _emit(
            "FIRMWARE IDENTITY DASHBOARD installed local-pc-file-does-not-skip-node-query=1 "
            "vanilla-fallback-hidden-while-probing=1"
        )

    reference_dashboard._build_dashboard = build_dashboard


def install(services: Any) -> None:
    """Keep flashing functional while making JARNSEN USB probing boot-safe."""
    if getattr(services, "_jarnsen_radio_profile_legacy_fallback", False):
        return

    # Patch both consumers before the dashboard starts its first background
    # firmware check. reference_dashboard imports these module functions later,
    # therefore it receives the stable identity implementation too.
    node_sync._raw_command = _stable_raw_command
    firmware_status_ui.query_jarnsen_identity = _stable_identity_query
    services.query_jarnsen_identity = _stable_identity_query
    _install_dashboard_identity_refresh(services)

    base_write_slots = node_sync._write_firmware_slots
    base_manual_sync = getattr(services, "sync_radio_profiles_to_node", None)

    def write_slots_compat(
        port: str,
        settings: dict[str, Any],
        active_before: str,
        standard_region: str,
        runtime_services: Any,
    ) -> None:
        key = _port_key(port)
        if key in _UNSUPPORTED_PORTS:
            _emit(
                "RADIO NODE SYNC slot-write skipped "
                f"port={port} reason=firmware-service-unavailable standard-restored=1 "
                "jarnsen-slots-deferred=1"
            )
            return
        try:
            base_write_slots(
                port, settings, active_before, standard_region, runtime_services
            )
        except TimeoutError as exc:
            _UNSUPPORTED_PORTS.add(key)
            _emit(
                "RADIO NODE SYNC slot-write compatibility-fallback "
                f"port={port} reason=slot-command-timeout standard-restored=1 "
                f"jarnsen-slots-deferred=1 type={type(exc).__name__}"
            )
            return

    node_sync._read_active_profile = _compat_active_profile
    node_sync._write_firmware_slots = write_slots_compat

    if callable(base_manual_sync):

        def manual_sync(port: str) -> None:
            key = _port_key(port)
            _UNSUPPORTED_PORTS.discard(key)
            base_manual_sync(port)
            if key in _UNSUPPORTED_PORTS:
                raise RuntimeError(
                    "Die installierte Firmware unterstützt die 3 Funkprofil-Slots noch nicht. "
                    "Standard wurde nicht beschädigt; Jarnsen 1/2 können erst mit einer Firmware "
                    "mit JARNSEN_TOOL_RADIO-Unterstützung in die Node geschrieben werden."
                )

        services.sync_radio_profiles_to_node = manual_sync

    services._jarnsen_radio_profile_legacy_fallback = True
    services.radio_profile_slots_supported = (
        lambda port: _port_key(port) not in _UNSUPPORTED_PORTS
    )

    _emit(
        "RADIO NODE SYNC LEGACY FALLBACK installed probe-timeout=7s attempts=1 "
        "vanilla-no-fatal=1 standard-restore-continues=1 slot-write-deferred=1 "
        "identity-resend=1 boot-ready-resend=1 pc-file-identity-query=1 "
        "unterminated-service-line=1 fragmented-line-safe=1 ansi-safe=1"
    )
