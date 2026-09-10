from __future__ import annotations

import os
import re
import threading
import time
from typing import Any


_INSTALLED = False
_FLASH_GATE = threading.RLock()
_MODE_CONTEXT = threading.local()
_RELEASE_CACHE: tuple[float, list[dict[str, Any]]] = (0.0, [])
_RELEASE_CACHE_LOCK = threading.Lock()


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _text(exc: BaseException) -> str:
    return str(exc or "").casefold()


def _transient_usb_error(exc: BaseException) -> bool:
    value = _text(exc)
    return any(
        token in value
        for token in (
            "permissionerror",
            "clearcommerror",
            "cannot configure port",
            "zugriff verweigert",
            "das gerät erkennt den befehl nicht",
            "das ger�t erkennt den befehl nicht",
            "device does not recognize the command",
            "could not open port",
            "doesn't exist",
            "filenotfounderror",
        )
    )


def _release_list(services: Any) -> list[dict[str, Any]]:
    global _RELEASE_CACHE
    now = time.monotonic()
    with _RELEASE_CACHE_LOCK:
        stamp, cached = _RELEASE_CACHE
        if cached and now - stamp < 90.0:
            return list(cached)
    client = services.GitHubFirmwareClient()
    payload = client._get_json(
        f"{client.api}/repos/{services.REPOSITORY}/releases",
        per_page=50,
    )
    releases = list(payload or []) if isinstance(payload, list) else list(payload.get("releases", []) or [])
    with _RELEASE_CACHE_LOCK:
        _RELEASE_CACHE = (time.monotonic(), releases)
    return releases


def _release_identity_from_scan(services: Any, port: str):
    import firmware_identity_sha_match as sha_layer
    import firmware_status_ui as status

    key = str(port or "").strip().upper()
    with sha_layer._CACHE_LOCK:
        board_key, model_text = sha_layer._SCAN_BY_PORT.get(key, (None, ""))
    if board_key not in services.BOARD_PROFILES or not model_text:
        return None

    reported = status.parse_installed_firmware(model_text)
    if bool(getattr(reported, "is_jarnsen", False)):
        return reported
    sha = sha_layer._git_sha_from_version(str(getattr(reported, "version", "") or ""))
    if not sha:
        return None

    profile = services.BOARD_PROFILES[board_key]
    wanted_prefix = str(profile.get("artifact_prefix") or "")
    for release in _release_list(services):
        if release.get("draft"):
            continue
        target = str(release.get("target_commitish") or "").strip().lower()
        if not target or not (target.startswith(sha) or sha.startswith(target)):
            continue
        assets = list(release.get("assets") or [])
        if wanted_prefix and not any(
            str(asset.get("name") or "").startswith(wanted_prefix)
            and str(asset.get("name") or "").endswith("-package-manifest.json")
            for asset in assets
        ):
            continue
        tag = str(release.get("tag_name") or "").strip()
        version = tag[1:] if tag.lower().startswith("v") else tag
        name = str(release.get("name") or "")
        match = re.search(r"(?i)\bBuild\s*#?\s*(\d+)\b", name)
        if not version or not match:
            continue
        identity = status.FirmwareIdentity(
            product="JARNSEN-MESH",
            version=version,
            build=int(match.group(1)),
            edition="JARNSEN-MESH",
            hardware=str(profile.get("label") or board_key),
            sha=target,
        )
        with sha_layer._CACHE_LOCK:
            sha_layer._TRUSTED_BY_PORT[key] = identity
            sha_layer._TRUSTED_AT_BY_PORT[key] = time.monotonic()
        _emit(
            f"FIRMWARE RELEASE SHA MATCH port={key} board={board_key} sha={sha} "
            f"tag={tag!r} build={identity.build} target={target[:12]} manifest=1"
        )
        return identity
    return None


def _patch_identity(services: Any) -> None:
    import firmware_status_ui as status

    base = services.query_jarnsen_identity

    def query(port: str, timeout: float = 1.8):
        try:
            identity = _release_identity_from_scan(services, port)
            if identity is not None:
                return identity
        except Exception as exc:
            _emit(
                f"FIRMWARE RELEASE SHA LOOKUP FAILED port={port} "
                f"type={type(exc).__name__} message={str(exc)[:320]!r}"
            )
        return base(port, timeout=timeout)

    services.query_jarnsen_identity = query
    status.query_jarnsen_identity = query
    services._jarnsen_release_sha_identity = True


def _find_supreme_port(original_port: str, timeout: float = 10.0) -> str:
    original = str(original_port or "").strip().upper()
    try:
        from serial.tools import list_ports
    except Exception:
        return original

    serial_number = ""
    try:
        for item in list_ports.comports():
            if str(getattr(item, "device", "") or "").upper() == original:
                serial_number = str(getattr(item, "serial_number", "") or "").strip()
                break
    except Exception:
        pass

    deadline = time.monotonic() + max(0.5, float(timeout))
    last = ""
    while time.monotonic() < deadline:
        try:
            matches = []
            for item in list_ports.comports():
                device = str(getattr(item, "device", "") or "").strip()
                if not device:
                    continue
                vid = getattr(item, "vid", None)
                pid = getattr(item, "pid", None)
                serial = str(getattr(item, "serial_number", "") or "").strip()
                if vid == 0x303A and pid == 0x1001:
                    if serial_number and serial and serial == serial_number:
                        return device
                    matches.append(device)
                if device.upper() == original:
                    last = device
            if len(matches) == 1:
                return matches[0]
            if last:
                return last
        except Exception:
            pass
        time.sleep(0.20)
    return last or original


def _patch_supreme_flash(services: Any) -> None:
    import unified_service_v2 as unified

    base = unified.flash_firmware_only_bundle

    def hardened(services_arg: Any, port: str, board_key: str, bundle: Any, log: Any) -> None:
        if str(board_key or "").strip().lower() != "tbeam_supreme":
            return base(services_arg, port, board_key, bundle, log)

        from pathlib import Path

        update_image = Path(bundle.update)
        targets = list(getattr(bundle, "flash_targets", []) or unified._esp32_update_targets(bundle))
        selected = str(getattr(services_arg, "_jarnsen_flash_baud", "921600"))
        candidates = tuple(
            getattr(services_arg, "flash_baud_candidates", lambda value: (str(value),))(selected)
        )
        retryable = getattr(services_arg, "is_retryable_flash_error", lambda _exc: False)
        flash_port = _find_supreme_port(port, timeout=1.0)

        if log:
            log(
                "BOOTLOADER · ESP32-S3 USB-Serial/JTAG · atomarer esptool USB-Reset + Schreibvorgang aktiv"
            )

        with _FLASH_GATE:
            last_error: BaseException | None = None
            for index, baud in enumerate(candidates, start=1):
                common = [
                    "--chip", "esp32s3",
                    "--before", "usb-reset",
                    "--after", "watchdog-reset",
                    "--baud", str(baud),
                    "write-flash", "--flash-mode", "dio",
                    "--flash-freq", "80m", "--flash-size", "keep",
                ]
                same_baud_attempts = 2
                for same_attempt in range(1, same_baud_attempts + 1):
                    try:
                        if same_attempt > 1:
                            flash_port = _find_supreme_port(flash_port or port, timeout=10.0)
                            if log:
                                log(
                                    f"RECOVERY · Supreme USB-Neuanmeldung bestätigt · Port={flash_port} · "
                                    f"gleicher Baudrate-Versuch {same_attempt}/{same_baud_attempts}"
                                )
                        unified._write_update_slots(
                            services_arg, flash_port, common, update_image, targets, log
                        )
                        services_arg._jarnsen_flash_baud = str(baud)
                        _emit(
                            f"SUPREME ATOMIC FLASH OK port={flash_port} baud={baud} "
                            f"targets={len(targets)} usb-reset=same-process"
                        )
                        return
                    except Exception as exc:
                        last_error = exc
                        if same_attempt < same_baud_attempts and _transient_usb_error(exc):
                            if log:
                                log(
                                    "RECOVERY · Windows hat den nativen ESP32-S3-Port beim USB-Reset "
                                    "kurz entfernt · auf Neuanmeldung warten"
                                )
                            time.sleep(0.6)
                            continue
                        break

                if index >= len(candidates) or not (
                    _transient_usb_error(last_error or RuntimeError())
                    or retryable(last_error or RuntimeError())
                ):
                    break
                if log:
                    log(
                        f"RECOVERY · Supreme-Update bei {baud} Baud nicht stabil · "
                        f"nächster Versuch mit {candidates[index]} Baud"
                    )
                time.sleep(0.8)

        raise services_arg.FlasherError(
            "SUPREME_BOOTLOADER_SYNC: Der ESP32-S3 konnte trotz atomarem USB-Reset "
            "und bestätigter USB-Neuanmeldung nicht beschrieben werden.\n"
            + str(last_error or "unbekannter USB-Fehler")
        )

    unified.flash_firmware_only_bundle = hardened
    services._jarnsen_supreme_atomic_flash = True


def _patch_serial_gate(services: Any) -> None:
    base_meshtastic = services.meshtastic

    def meshtastic(port: str, *args: str, **kwargs: Any):
        with _FLASH_GATE:
            return base_meshtastic(port, *args, **kwargs)

    services.meshtastic = meshtastic


def _patch_ui_geometry() -> None:
    import profile_progress_ui

    base = profile_progress_ui._apply_reference_geometry

    def apply(app: Any) -> None:
        base(app)
        try:
            cards = list(app.body.winfo_children())
            if len(cards) != 8:
                return
            device, profile, identity, service, firmware, automatic, hints, protocol = cards
            hardened = (
                (device, 0.000, 0.000, 1.000, 0.181),
                (profile, 0.000, 0.190, 0.496, 0.191),
                (identity, 0.504, 0.190, 0.496, 0.176),
                (service, 0.000, 0.390, 0.496, 0.112),
                (firmware, 0.504, 0.375, 0.496, 0.166),
                (automatic, 0.000, 0.511, 0.496, 0.224),
                (hints, 0.504, 0.553, 0.496, 0.182),
                (protocol, 0.000, 0.744, 1.000, 0.240),
            )
            for widget, relx, rely, relwidth, relheight in hardened:
                widget.place_configure(relx=relx, rely=rely, relwidth=relwidth, relheight=relheight)
            for child in profile.winfo_children():
                try:
                    info = child.pack_info()
                    pady = info.get("pady", 0)
                    if isinstance(pady, tuple):
                        top, bottom = pady
                        child.pack_configure(pady=(min(int(top), 4), min(int(bottom), 4)))
                except Exception:
                    pass

            toggle = None
            stack = [protocol]
            while stack:
                node = stack.pop()
                try:
                    stack.extend(node.winfo_children())
                except Exception:
                    pass
                try:
                    if node.__class__.__name__ == "CTkButton" and str(node.cget("text") or "") in {"PROTOKOLL GROSS", "PROTOKOLL KOMPAKT"}:
                        toggle = node
                        break
                except Exception:
                    pass
            if toggle is not None:
                expanded = {"value": False}

                def restore_hardened() -> None:
                    for widget, relx, rely, relwidth, relheight in hardened:
                        widget.place(relx=relx, rely=rely, relwidth=relwidth, relheight=relheight)

                def toggle_protocol() -> None:
                    expanded["value"] = not expanded["value"]
                    if expanded["value"]:
                        for widget in (profile, identity, service, firmware, automatic, hints):
                            widget.place_forget()
                        protocol.place(relx=0.0, rely=0.190, relwidth=1.0, relheight=0.794)
                        toggle.configure(text="PROTOKOLL KOMPAKT")
                    else:
                        restore_hardened()
                        toggle.configure(text="PROTOKOLL GROSS")

                toggle.configure(command=toggle_protocol)

            _emit(
                "REFERENCE GEOMETRY hardening profile-height=0.191 service-y=0.390 "
                "automatic-y=0.511 two-line-actions-unclipped=1 toggle-restore=1"
            )
        except Exception as exc:
            _emit(f"REFERENCE GEOMETRY hardening skipped {type(exc).__name__}:{exc}")

    profile_progress_ui._apply_reference_geometry = apply


def _patch_flash_mode_compat(services: Any) -> None:
    import customtkinter as ctk

    original_root_init = ctk.CTk.__init__

    def root_init(app: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(app, *args, **kwargs)

        def wrap_preflight() -> None:
            current = getattr(services, "run_flash_preflight", None)
            if not callable(current) or getattr(current, "_jarnsen_mode_context", False):
                return

            def preflight(port: str, board_key: str, bundle: Any, mode: str = "repair", *a: Any, **kw: Any):
                requested = getattr(_MODE_CONTEXT, "flash_mode", None)
                effective = str(requested or mode or "repair")
                return current(port, board_key, bundle, effective, *a, **kw)

            preflight._jarnsen_mode_context = True
            services.run_flash_preflight = preflight

        def wrap_perform() -> None:
            wrap_preflight()
            current = getattr(app, "_perform_flash", None)
            if not callable(current) or getattr(current, "_jarnsen_flash_mode_compat", False):
                return

            def perform(
                port: str,
                board_key: str,
                long_name: str,
                short_name: str,
                *,
                series_index: int | None = None,
                strict_preflight: bool = False,
                flash_mode: str = "repair",
            ):
                previous = getattr(_MODE_CONTEXT, "flash_mode", None)
                _MODE_CONTEXT.flash_mode = str(flash_mode or "repair")
                try:
                    return current(
                        port,
                        board_key,
                        long_name,
                        short_name,
                        series_index=series_index,
                        strict_preflight=strict_preflight,
                    )
                finally:
                    if previous is None:
                        try:
                            delattr(_MODE_CONTEXT, "flash_mode")
                        except Exception:
                            pass
                    else:
                        _MODE_CONTEXT.flash_mode = previous

            perform._jarnsen_flash_mode_compat = True
            app._perform_flash = perform
            _emit("FLASH MODE COMPAT attached accepts-flash_mode=1 preserves-preflight-mode=1")

        for delay in (0, 350, 900, 1800, 2800):
            try:
                app.after(delay, wrap_perform)
            except Exception:
                pass

    ctk.CTk.__init__ = root_init


def install(services: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"

    _patch_identity(services)
    _patch_supreme_flash(services)
    _patch_serial_gate(services)
    _patch_ui_geometry()
    _patch_flash_mode_compat(services)

    services._jarnsen_build261_hardening = True
    _emit(
        "BUILD261 HARDENING installed release-sha-identity=1 supreme-atomic-usb-reset=1 "
        "profile-clipping-fix=1 flash-mode-compat=1 utf8-child-output=1 flash-exclusive-gate=1"
    )
