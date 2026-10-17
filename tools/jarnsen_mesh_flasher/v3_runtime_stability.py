from __future__ import annotations

import time
import types
from typing import Any

import customtkinter as ctk

_INSTALLED = False
_KNOWN_FLASH_TTL = 15 * 60.0


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


def _exception_output(exc: BaseException) -> str:
    return "\n".join(
        part
        for part in (
            _decode(getattr(exc, "stdout", "")),
            _decode(getattr(exc, "stderr", "")),
            _decode(getattr(exc, "output", "")),
        )
        if part
    )


def _port_key(port: str) -> str:
    return str(port or "").strip().upper()


def _is_v3_info(text: str) -> bool:
    upper = str(text or "").upper()
    return "CONNECTED TO RADIO" in upper and (
        "HELTEC_V3" in upper
        or "HELTEC-V3" in upper
        or "HELTEC V3" in upper
        or 'PIOENV": "HELTEC-V3' in upper
    )


def _wait_v3_meshtastic_ready(services: Any, port: str, timeout: float = 90.0) -> str:
    """Wait for the V3 application protocol, not merely for the COM port.

    ESP32-S3/CP210x keeps the COM device visible while the freshly flashed V3 is
    still booting. A plain wait_for_serial therefore returns too early. Accept a
    timeout result too when stdout already proves that Meshtastic answered and
    identified the V3; some CLI versions keep --info open longer than necessary.
    """
    started = time.monotonic()
    deadline = started + max(20.0, float(timeout))
    attempt = 0
    last_output = ""

    while time.monotonic() < deadline:
        attempt += 1
        remaining = max(1.0, deadline - time.monotonic())
        attempt_timeout = int(max(8.0, min(22.0, remaining)))
        output = ""
        try:
            result = services.meshtastic(
                port,
                "--info",
                timeout=attempt_timeout,
                check=False,
            )
            output = "\n".join(
                part
                for part in (_decode(result.stdout), _decode(result.stderr))
                if part
            )
        except Exception as exc:
            output = _exception_output(exc)
            _emit(
                f"V3 BOOT READY probe-exception port={port} attempt={attempt} "
                f"type={type(exc).__name__} chars={len(output)}"
            )

        if output:
            last_output = output
        if _is_v3_info(output):
            elapsed = time.monotonic() - started
            _emit(
                f"V3 BOOT READY ok port={port} attempt={attempt} elapsed={elapsed:.1f}s "
                f"chars={len(output)}"
            )
            callback = getattr(services, "_jarnsen_ui_log_callback", None)
            if callable(callback):
                try:
                    callback(
                        f"V3 BOOT-READY · {port} · Meshtastic antwortet · {elapsed:.1f}s"
                    )
                except Exception:
                    pass
            return output

        if time.monotonic() < deadline:
            time.sleep(1.2)

    tail = last_output[-700:].replace("\r", " ").replace("\n", " | ")
    _emit(
        f"V3 BOOT READY timeout port={port} attempts={attempt} "
        f"elapsed={time.monotonic() - started:.1f}s tail={tail!r}"
    )
    raise services.FlasherError(
        "Heltec V3 ist am COM-Port sichtbar, aber die Meshtastic-Schnittstelle "
        "ist nach dem Flash noch nicht betriebsbereit. Der Profil-Write wurde "
        "deshalb sicher angehalten, statt in einen Verbindungs-Timeout zu laufen."
    )


def install(services: Any) -> None:
    """V3-specific post-flash readiness and installed-firmware stabilization."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    import firmware_status_ui
    import native_actions
    import radio_profile_legacy_fallback as legacy
    import radio_profile_node_sync as node_sync
    import radio_profiles
    import reference_dashboard

    board_by_port: dict[str, str] = {}
    known_flash_by_port: dict[str, dict[str, Any]] = {}
    services._jarnsen_operation_board_by_port = board_by_port
    services._jarnsen_known_flash_by_port = known_flash_by_port

    # ------------------------------------------------------------------ V3 radio/profile preflight
    base_compat_active_profile = legacy._compat_active_profile

    def compat_active_profile(port: str, runtime_services: Any) -> str:
        key = _port_key(port)
        board_key = str(board_by_port.get(key, "") or "")
        if board_key != "repeater":
            return base_compat_active_profile(port, runtime_services)

        # Important for V3: after esptool reset the CP210x COM port is already
        # visible while Meshtastic is still starting. Do not send an additional
        # meshtastic --reboot here. First prove the application protocol is alive.
        _wait_v3_meshtastic_ready(runtime_services, port, timeout=90.0)

        try:
            line = node_sync._raw_command(
                port,
                "JARNSEN_TOOL_RADIO_INFO",
                expected=node_sync.RADIO_INFO_MARKER,
                timeout=legacy.PROBE_TIMEOUT,
            )
            match = node_sync.ACTIVE_RE.search(line)
            if not match:
                raise RuntimeError(
                    f"Aktives Funkprofil konnte nicht aus der Firmware-Antwort gelesen werden: {line}"
                )
            active = match.group(1).lower()
            try:
                from radio_profile_runtime_stability import _record_slot_probe

                _record_slot_probe(runtime_services, port, True)
            except Exception:
                pass
            legacy._UNSUPPORTED_PORTS.discard(key)
            _emit(
                f"V3 RADIO PREFLIGHT port={port} slots-supported=1 active={active} "
                "extra-reboot=0 boot-ready=1"
            )
            return active
        except (TimeoutError, RuntimeError) as exc:
            # The three persistent radio slots are optional for legacy/VANILLA-like
            # firmware. Standard still comes from the selected YAML profile. Most
            # importantly, no second reboot is injected before the 53 safe values.
            try:
                from radio_profile_runtime_stability import _record_slot_probe

                _record_slot_probe(runtime_services, port, False)
            except Exception:
                pass
            legacy._UNSUPPORTED_PORTS.add(key)
            _emit(
                f"V3 RADIO PREFLIGHT port={port} slots-supported=0 fallback=standard-only "
                f"extra-reboot=0 boot-ready=1 type={type(exc).__name__}"
            )
            return radio_profiles.PROFILE_STANDARD

    legacy._compat_active_profile = compat_active_profile
    node_sync._read_active_profile = compat_active_profile

    # ------------------------------------------------------------------ known-successful flash identity
    base_flash_bundle = services.flash_bundle

    def flash_bundle(port: str, bundle: Any, log=None) -> Any:
        result = base_flash_bundle(port, bundle, log=log)
        key = _port_key(port)
        board_key = str(getattr(bundle, "board_key", "") or "")
        if board_key == "repeater":
            known_flash_by_port[key] = {
                "timestamp": time.monotonic(),
                "version": str(getattr(bundle, "version", "") or "").strip(),
                "build": int(getattr(bundle, "run_number", 0) or 0),
                "board_key": board_key,
            }
            _emit(
                f"V3 FLASH IDENTITY remembered port={port} "
                f"version={known_flash_by_port[key]['version']!r} "
                f"build={known_flash_by_port[key]['build']} verified-write=1"
            )
        return result

    services.flash_bundle = flash_bundle

    def known_identity(port: str):
        item = known_flash_by_port.get(_port_key(port))
        if not item:
            return None
        if time.monotonic() - float(item.get("timestamp", 0.0)) > _KNOWN_FLASH_TTL:
            known_flash_by_port.pop(_port_key(port), None)
            return None
        version = str(item.get("version") or "").strip()
        build = int(item.get("build") or 0)
        if not version and not build:
            return None
        label = str(
            services.BOARD_PROFILES.get("repeater", {}).get("label") or "Heltec V3"
        )
        return firmware_status_ui.FirmwareIdentity(
            product="JARNSEN-MESH",
            version=version,
            build=build or None,
            edition="JARNSEN-MESH",
            hardware=label,
        )

    base_query_identity = services.query_jarnsen_identity

    def query_identity(port: str, timeout: float = 1.8):
        identity = None
        try:
            identity = base_query_identity(port, timeout=timeout)
        except Exception as exc:
            _emit(
                f"V3 FLASH IDENTITY exact-query-warning port={port} "
                f"type={type(exc).__name__} message={str(exc)[:300]!r}"
            )
        if identity is not None and bool(getattr(identity, "is_jarnsen", False)):
            return identity
        remembered = known_identity(port)
        if remembered is not None:
            _emit(
                f"V3 FLASH IDENTITY use-remembered port={port} "
                f"version={remembered.version!r} build={remembered.build!r}"
            )
            return remembered
        return identity

    services.query_jarnsen_identity = query_identity
    firmware_status_ui.query_jarnsen_identity = query_identity

    base_legacy_identity = legacy._stable_identity_query

    def stable_identity(port: str, timeout: float = 1.8):
        exact = None
        try:
            exact = base_legacy_identity(port, timeout=timeout)
        except Exception as exc:
            _emit(
                f"V3 FLASH IDENTITY legacy-query-warning port={port} "
                f"type={type(exc).__name__} message={str(exc)[:300]!r}"
            )
        return exact or known_identity(port)

    legacy._stable_identity_query = stable_identity

    # ------------------------------------------------------------------ board hint + post-operation refresh
    original_root_init = ctk.CTk.__init__

    def root_init(app: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(app, *args, **kwargs)

        def patch_app(attempt: int = 0) -> None:
            if getattr(app, "_jarnsen_v3_runtime_stability_ready", False):
                return
            original_perform = getattr(app, "_perform_flash", None)
            if not callable(original_perform):
                if attempt < 100:
                    try:
                        app.after(120, patch_app, attempt + 1)
                    except Exception:
                        pass
                return

            def schedule_identity_refresh() -> None:
                def refresh() -> None:
                    callback = getattr(app, "refresh_firmware_status", None)
                    if callable(callback):
                        try:
                            callback(force=True)
                        except TypeError:
                            callback()
                        except Exception as exc:
                            _emit(
                                f"V3 FLASH IDENTITY refresh-warning type={type(exc).__name__} "
                                f"message={str(exc)[:300]!r}"
                            )

                try:
                    app.after(1200, refresh)
                    app.after(6500, refresh)
                except Exception:
                    pass

            def perform_flash(
                app_self: Any,
                port: str,
                board_key: str,
                long_name: str,
                short_name: str,
                *,
                series_index: int | None = None,
                strict_preflight: bool = False,
            ) -> Any:
                key = _port_key(port)
                previous = board_by_port.get(key)
                board_by_port[key] = str(board_key or "")
                _emit(f"V3 OPERATION HINT set port={port} board={board_key!r}")
                try:
                    return original_perform(
                        port,
                        board_key,
                        long_name,
                        short_name,
                        series_index=series_index,
                        strict_preflight=strict_preflight,
                    )
                finally:
                    if previous is None:
                        board_by_port.pop(key, None)
                    else:
                        board_by_port[key] = previous
                    schedule_identity_refresh()

            app._perform_flash = types.MethodType(perform_flash, app)
            app._jarnsen_v3_runtime_stability_ready = True
            _emit("V3 RUNTIME UI ready perform-flash-board-hint=1 post-refresh=2")

        try:
            app.after(700, patch_app)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init

    # Profile-only starts its worker asynchronously, so retain the board hint until
    # app.busy becomes false. Patch both the source module and the dashboard's
    # imported symbol before the dashboard creates its button.
    base_profile_only = native_actions.start_profile_only

    def start_profile_only(app: Any, runtime_services: Any) -> Any:
        device = app._selected_device() if hasattr(app, "_selected_device") else None
        board_key = (
            app._selected_board_key() if hasattr(app, "_selected_board_key") else None
        )
        key = _port_key(getattr(device, "port", "")) if device is not None else ""
        if key and board_key:
            board_by_port[key] = str(board_key)
            _emit(f"V3 PROFILE-ONLY HINT set port={key} board={board_key!r}")

        result = base_profile_only(app, runtime_services)

        if key:

            def clear_when_done() -> None:
                try:
                    if getattr(app, "busy", False):
                        app.after(500, clear_when_done)
                        return
                except Exception:
                    pass
                board_by_port.pop(key, None)
                refresh = getattr(app, "refresh_firmware_status", None)
                if callable(refresh):
                    try:
                        refresh(force=True)
                    except TypeError:
                        refresh()
                    except Exception:
                        pass

            try:
                app.after(500, clear_when_done)
            except Exception:
                board_by_port.pop(key, None)
        return result

    native_actions.start_profile_only = start_profile_only
    reference_dashboard.start_profile_only = start_profile_only

    services.wait_v3_meshtastic_ready = (
        lambda port, timeout=90: _wait_v3_meshtastic_ready(
            services, port, timeout=float(timeout)
        )
    )
    services._jarnsen_v3_runtime_stability = True
    _emit(
        "V3 RUNTIME STABILITY installed boot-ready=meshtastic-info no-preprofile-reboot=1 "
        "known-flash-identity=1 post-operation-refresh=2 profile-only-board-hint=1"
    )
