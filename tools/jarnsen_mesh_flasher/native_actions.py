from __future__ import annotations

import re
import subprocess
import threading
import time
from pathlib import Path
from tkinter import messagebox
from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


AUTO_FIRMWARE_SELECTION = "Automatisch (neueste)"


_FUNCTION_LABEL_BY_ID = {
    "tak": "TAK",
    "tak_tracker": "TAK TRACKER",
    "tak_repeater": "TAK REPEATER",
    "drone_repeater": "DRONE REPEATER",
}


def _decode_process_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _setting_value(text: str, *names: str) -> str:
    for name in names:
        match = re.search(
            rf'"{re.escape(name)}"\s*:\s*(?:"([^"]*)"|(-?\d+(?:\.\d+)?)|(true|false))',
            text or "",
            re.IGNORECASE,
        )
        if match:
            return next((part for part in match.groups() if part is not None), "")
    return ""


def _basic_settings_from_info(text: str) -> dict[str, str]:
    from profile_utils import info_json_section

    lora = info_json_section(text, "Preferences").get("lora")
    if isinstance(lora, dict):
        return {
            "region": str(lora.get("region", "")),
            "modem": str(lora.get("modemPreset", lora.get("modem_preset", ""))),
            "hops": str(lora.get("hopLimit", lora.get("hop_limit", ""))),
            "tx": str(lora.get("txPower", lora.get("tx_power", ""))),
        }
    return {
        "region": _setting_value(text, "region"),
        "modem": _setting_value(text, "modemPreset", "modem_preset"),
        "hops": _setting_value(text, "hopLimit", "hop_limit"),
        "tx": _setting_value(text, "txPower", "tx_power"),
    }


def _functional_identifier_from_node(
    service_role: str, meshtastic_role: str, board_key: str
) -> str:
    service = re.sub(
        r"[^a-z0-9]+", "_", str(service_role or "").strip().casefold()
    ).strip("_")
    if service in _FUNCTION_LABEL_BY_ID:
        return service

    role = re.sub(r"[^A-Z0-9]+", "_", str(meshtastic_role or "").strip().upper()).strip(
        "_"
    )
    if role == "TAK":
        return "tak"
    if role == "TAK_TRACKER":
        return "tak_tracker"
    if role == "ROUTER_LATE" and str(board_key or "").strip().lower() == "repeater":
        return "tak_repeater"
    return ""


def sync_functional_profile_menu(
    app: Any, services: Any, board_key: str | None
) -> None:
    menu = getattr(app, "functional_profile_menu", None)
    variable = getattr(app, "functional_profile_var", None)
    if menu is None or variable is None:
        return

    try:
        import functional_profiles as fp

        board = str(board_key or "").strip().lower()
        values = [
            item.label
            for item in fp.FUNCTIONAL_PROFILES
            if not board or fp.compatibility_for_board(item, board, services)[0]
        ]
        if not values:
            values = list(fp.labels())
        menu.configure(values=values)
        current = str(variable.get() or "").strip()
        if current and current not in values and current != fp.SELECT_PLACEHOLDER:
            variable.set(fp.SELECT_PLACEHOLDER)
    except Exception as exc:
        _emit(
            "FUNCTION MENU SYNC ERROR "
            f"board={board_key!r} type={type(exc).__name__} message={exc}"
        )


def _read_role_service(services: Any, port: str) -> tuple[str, str]:
    try:
        import review_team_provisioning_v2 as provisioning

        line = provisioning._raw_command(
            port,
            "JARNSEN_TOOL_ROLE_INFO",
            expected="===JARNSEN_ROLE===",
            timeout=3.5,
            attempts=1,
            services=services,
        )
        data = provisioning._parse_role_info(line)
        return str(data.get("role", "") or ""), line
    except Exception as exc:
        _emit(
            f"NODE STATE ROLE SERVICE MISS port={port} "
            f"type={type(exc).__name__} message={str(exc)[:240]!r}"
        )
        return "", ""


def _node_info_complete(info: str) -> bool:
    from profile_utils import summary_from_info_text

    summary = summary_from_info_text(info)
    settings = _basic_settings_from_info(info)
    return bool(
        re.search(r"(?m)^Owner:", info)
        and summary.long_name
        and summary.role
        and all(settings.values())
    )


def _read_node_info_text(services: Any, port: str, timeout: int = 30) -> str:
    info = ""
    for attempt in range(2):
        try:
            result = services.meshtastic(port, "--info", timeout=timeout, check=False)
            info = "\n".join(
                part
                for part in (
                    _decode_process_text(getattr(result, "stdout", "")),
                    _decode_process_text(getattr(result, "stderr", "")),
                )
                if part.strip()
            )
        except subprocess.TimeoutExpired as exc:
            info = "\n".join(
                part
                for part in (
                    _decode_process_text(exc.stdout),
                    _decode_process_text(exc.stderr),
                )
                if part.strip()
            )
        if _node_info_complete(info):
            return info
        if attempt == 0:
            _emit(
                f"NODE STATE RETRY port={port} reason=incomplete-or-usb-error fresh-info=1 reset=0"
            )
            time.sleep(1.0)
    raise services.FlasherError(
        f"{port}: Node-Daten nicht vollständig gelesen. "
        f"{info.strip()[-450:] or 'Keine Antwort auf die Einstellungsabfrage.'}"
    )


def _set_identity_read_state(app: Any, text: str, state: str) -> None:
    variable = getattr(app, "node_identity_state_var", None)
    if variable is not None:
        variable.set(text)
    bar = getattr(app, "node_identity_bar", None)
    if bar is not None:
        colors = {"ok": ("#143B2C", "#1F6A48"), "error": ("#432B16", "#9A611F")}
        fill, border = colors.get(state, ("#15273A", "#344A5F"))
        bar.configure(fg_color=fill, border_color=border)


def _node_state_summary(
    *, service_role: str, meshtastic_role: str, settings: dict[str, str]
) -> str:
    function_label = _FUNCTION_LABEL_BY_ID.get(
        re.sub(r"[^a-z0-9]+", "_", str(service_role or "").casefold()).strip("_"),
        "",
    )
    role_text = function_label or meshtastic_role or "unbekannt"
    parts = [f"Node · Rolle: {role_text}"]
    if function_label and meshtastic_role:
        expected = {
            "TAK": "TAK",
            "TAK TRACKER": "TAK_TRACKER",
            "TAK REPEATER": "ROUTER_LATE",
            "DRONE REPEATER": "ROUTER_LATE",
        }.get(function_label, "")
        if expected and meshtastic_role.strip().upper() != expected:
            parts[0] += f" ⚠ Meshtastic={meshtastic_role}"
    if settings.get("region"):
        parts.append(f"Region {settings['region']}")
    if settings.get("modem"):
        parts.append(settings["modem"])
    if settings.get("hops"):
        parts.append(f"Hops {settings['hops']}")
    if settings.get("tx"):
        parts.append(f"TX {settings['tx']} dBm")
    return "   ·   ".join(parts)


def refresh_connected_node_state(
    app: Any,
    services: Any,
    *,
    show_details: bool = False,
    info_override: str | None = None,
) -> None:
    if bool(getattr(app, "busy", False)):
        return
    device = app._selected_device()
    node_var = getattr(app, "node_settings_var", None)
    if device is None:
        if node_var is not None:
            node_var.set("Node · kein Gerät verbunden")
        sync_functional_profile_menu(app, services, None)
        _set_identity_read_state(app, "Node-Daten noch nicht gelesen", "pending")
        return

    port = str(device.port)
    owns_read = info_override is None
    if owns_read and getattr(app, "_jarnsen_node_read_port", None) == port:
        if show_details:
            app._jarnsen_node_details_requested = True
        return
    if owns_read:
        app._jarnsen_node_read_port = port
        app._jarnsen_node_details_requested = show_details
        if show_details:
            app._set_busy(True)
            app._set_status(f"Vollständige Node-Daten von {port} lesen …")
    generation = int(getattr(app, "_jarnsen_node_state_generation", 0) or 0) + 1
    app._jarnsen_node_state_generation = generation
    board_key = app._selected_board_key()
    _set_identity_read_state(app, "Node-Daten werden gelesen …", "pending")
    if node_var is not None:
        node_var.set(f"Node · {port} · Rolle/Namen/Grundeinstellungen werden gelesen …")

    def worker() -> None:
        try:
            info = (
                info_override
                if info_override is not None
                else _read_node_info_text(services, port, timeout=30)
            )
            if not _node_info_complete(info):
                raise services.FlasherError(
                    f"{port}: Namen, Rolle und Grundeinstellungen wurden nicht vollständig gelesen."
                )
            from profile_utils import summary_from_info_text

            summary = summary_from_info_text(info)
            detected = services.detect_board_from_text(info)
            effective_board = detected or board_key
            service_role = _read_role_service(services, port)[0] if owns_read else ""
            settings = _basic_settings_from_info(info)
            identifier = _functional_identifier_from_node(
                service_role, summary.role, effective_board or ""
            )

            def update() -> None:
                if generation != int(
                    getattr(app, "_jarnsen_node_state_generation", 0) or 0
                ):
                    return
                selected = app._selected_device()
                if selected is None or str(selected.port).upper() != port.upper():
                    return
                if detected in services.BOARD_PROFILES:
                    selected.board_key = detected
                markers = [
                    line
                    for line in str(
                        getattr(selected, "model_text", "") or ""
                    ).splitlines()
                    if "===JARNSEN_INFO===" in line
                ]
                selected.model_text = "\n".join([info, *markers])
                if hasattr(app, "long_name_var"):
                    app.long_name_var.set(summary.long_name)
                if hasattr(app, "short_name_var"):
                    app.short_name_var.set(summary.short_name)

                sync_functional_profile_menu(app, services, effective_board)
                functional_var = getattr(app, "functional_profile_var", None)
                if identifier and functional_var is not None:
                    label = _FUNCTION_LABEL_BY_ID.get(identifier, "")
                    try:
                        import functional_profiles as fp

                        allowed = fp.compatibility_for_board(
                            identifier, effective_board, services
                        )[0]
                    except Exception:
                        allowed = False
                    if allowed and label:
                        functional_var.set(label)

                if node_var is not None:
                    node_var.set(
                        _node_state_summary(
                            service_role=service_role,
                            meshtastic_role=summary.role,
                            settings=settings,
                        )
                    )
                app._append_log(
                    f"NODE STATE READ · Port={port} · Board={detected or 'unbekannt'} · "
                    f"Function={identifier or 'unbekannt'} · MeshtasticRole={summary.role or 'unbekannt'} · "
                    f"Long={summary.long_name!r} · Short={summary.short_name!r} · "
                    f"Region={settings.get('region') or '-'} · Hops={settings.get('hops') or '-'} · "
                    f"TX={settings.get('tx') or '-'}"
                )
                _set_identity_read_state(
                    app,
                    "Node-Daten gelesen | Namen für den nächsten Schreibvorgang",
                    "ok",
                )
                if owns_read and bool(
                    getattr(app, "_jarnsen_node_details_requested", False)
                ):
                    app._set_status("Node-Daten vollständig gelesen")
                    messagebox.showinfo("Node-Info", info.strip()[:5000], parent=app)
                refresh = getattr(app, "refresh_firmware_status", None)
                if owns_read and callable(refresh):
                    refresh()

            app.after(0, update)
        except Exception as exc:
            message = str(exc)

            def fail() -> None:
                if generation != int(
                    getattr(app, "_jarnsen_node_state_generation", 0) or 0
                ):
                    return
                if node_var is not None:
                    node_var.set(f"Node · Daten noch nicht lesbar · {message[:120]}")
                _set_identity_read_state(
                    app, "Node-Daten nicht vollständig gelesen", "error"
                )
                app._append_log(f"NODE STATE READ FAILED · Port={port} · {message}")
                if show_details:
                    app._set_status("Node-Daten nicht vollständig gelesen")
                sync_functional_profile_menu(app, services, board_key)

            app.after(0, fail)
        finally:
            if owns_read:

                def finish() -> None:
                    if getattr(app, "_jarnsen_node_read_port", None) == port:
                        app._jarnsen_node_read_port = None
                    if show_details:
                        app._set_busy(False)

                app.after(0, finish)

    threading.Thread(
        target=worker, name="jarnsen-connected-node-state", daemon=True
    ).start()


def queue_connected_node_state_refresh(
    app: Any, services: Any, *, delay_ms: int = 1250
) -> None:
    try:
        app._jarnsen_node_state_generation = (
            int(getattr(app, "_jarnsen_node_state_generation", 0) or 0) + 1
        )
        app.after(
            max(250, int(delay_ms)),
            lambda: refresh_connected_node_state(app, services),
        )
    except Exception:
        pass


def _candidate_menu_label(candidate: Any) -> str:
    source = (
        "Release"
        if str(getattr(candidate, "source_kind", "")) == "github-release"
        else "Actions"
    )
    version = str(getattr(candidate, "version", "") or "?")
    build = int(getattr(candidate, "build", 0) or 0)
    return f"v{version} · B{build or '?'} · {source}"


def _same_candidate(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    return (
        str(getattr(left, "version", "")),
        int(getattr(left, "build", 0) or 0),
        str(getattr(left, "source_kind", "")),
    ) == (
        str(getattr(right, "version", "")),
        int(getattr(right, "build", 0) or 0),
        str(getattr(right, "source_kind", "")),
    )


def sync_firmware_version_menu(app: Any, services: Any, board_key: str) -> None:
    menu = getattr(app, "firmware_version_menu", None)
    variable = getattr(app, "firmware_version_var", None)
    if menu is None or variable is None:
        return
    cached_getter = getattr(services, "cached_unified_firmware_sources", None)
    candidates = list(cached_getter(board_key)) if callable(cached_getter) else []
    values = [AUTO_FIRMWARE_SELECTION]
    mapping: dict[str, Any] = {AUTO_FIRMWARE_SELECTION: None}
    for candidate in candidates:
        label = _candidate_menu_label(candidate)
        if label not in mapping:
            mapping[label] = candidate
            values.append(label)
    app._jarnsen_firmware_version_map = mapping

    selected_getter = getattr(services, "selected_unified_firmware_source", None)
    selected = selected_getter(board_key) if callable(selected_getter) else None
    chosen = AUTO_FIRMWARE_SELECTION
    if selected is not None:
        for label, candidate in mapping.items():
            if _same_candidate(candidate, selected):
                chosen = label
                break
        else:
            clearer = getattr(services, "clear_unified_firmware_source", None)
            if callable(clearer):
                clearer(board_key)
    try:
        menu.configure(values=values, state="normal")
        variable.set(chosen)
    except Exception:
        pass


def _invalidate_firmware_status_cache(services: Any, board_key: str) -> None:
    invalidator = getattr(services, "invalidate_available_firmware_cache", None)
    if callable(invalidator):
        invalidator(board_key)
        return
    try:
        import firmware_status_ui

        firmware_status_ui.invalidate_available_cache(board_key)
    except Exception:
        pass


def select_firmware_version(app: Any, services: Any, label: str) -> None:
    board_key = app._selected_board_key()
    if board_key not in services.BOARD_PROFILES:
        return
    mapping = getattr(app, "_jarnsen_firmware_version_map", {})
    candidate = mapping.get(str(label))
    services._jarnsen_local_firmware_bundle = None
    clearer = getattr(services, "clear_unified_firmware_source", None)
    selector = getattr(services, "select_unified_firmware_source", None)
    if candidate is None:
        if callable(clearer):
            clearer(board_key)
        app._append_log(
            f"FIRMWAREAUSWAHL · Board={board_key} · automatisch neueste Version"
        )
        app.firmware_var.set("Automatisch: neueste verfügbare Firmware")
    else:
        if not callable(selector):
            app._show_error(
                services.FlasherError("Firmware-Versionsauswahl ist nicht installiert.")
            )
            return
        selector(board_key, candidate)
        app._append_log(
            f"FIRMWAREAUSWAHL · Board={board_key} · "
            f"v{candidate.version} Build {candidate.build} · {candidate.source_label}"
        )
        app.firmware_var.set(
            f"Ausgewählt: JARNSEN-MESH v{candidate.version} · "
            f"{services.BOARD_PROFILES[board_key]['label']} · Build #{candidate.build}"
        )
    app.bundle = None
    _invalidate_firmware_status_cache(services, board_key)
    refresh = getattr(app, "refresh_firmware_status", None)
    if callable(refresh):
        app.after(80, lambda: refresh(force=False))


def refresh_firmware_versions(app: Any, services: Any) -> None:
    board_key = app._selected_board_key()
    if board_key not in services.BOARD_PROFILES:
        messagebox.showwarning(
            "Board unbekannt",
            "Bitte das Board zuerst erkennen oder manuell auswählen.",
            parent=app,
        )
        return
    menu = getattr(app, "firmware_version_menu", None)
    if menu is not None:
        try:
            menu.configure(state="disabled")
        except Exception:
            pass
    app._set_status("Firmware-Versionen von GitHub laden …")

    def worker() -> None:
        try:
            lister = getattr(services, "list_unified_firmware_sources", None)
            if not callable(lister):
                raise services.FlasherError(
                    "Firmware-Versionsliste ist nicht verfügbar."
                )
            candidates = list(
                lister(services.GitHubFirmwareClient(), board_key, force=True)
            )
            _invalidate_firmware_status_cache(services, board_key)

            def ready() -> None:
                sync_firmware_version_menu(app, services, board_key)
                app._set_status(
                    f"{len(candidates)} Firmware-Version(en) für "
                    f"{services.BOARD_PROFILES[board_key]['label']} verfügbar"
                )
                refresh = getattr(app, "refresh_firmware_status", None)
                if callable(refresh):
                    refresh(force=False)

            app.after(0, ready)
        except Exception as exc:

            def fail() -> None:
                if menu is not None:
                    try:
                        menu.configure(state="normal")
                    except Exception:
                        pass
                app._show_error(exc)

            app.after(0, fail)

    threading.Thread(
        target=worker, name="jarnsen-firmware-version-list", daemon=True
    ).start()


def choose_profile(app: Any, services: Any) -> None:
    # The main dashboard exposes only the four functional roles.
    from functional_profiles import activate_selected_functional_profile

    activate_selected_functional_profile(app, services)


def edit_current_profile(app: Any, services: Any) -> None:
    from profile_editor import open_profile_editor
    from profile_utils import summary_from_profile_file

    raw = str(app.profile_path_var.get() or "").strip()
    path = (
        Path(raw)
        if raw and raw != "Kein Profil geladen"
        else Path(services.PATHS.active_profile)
    )
    if not path.exists():
        messagebox.showwarning(
            "Profil bearbeiten",
            "Bitte zuerst ein Profil auswählen oder vom Master einlesen.",
            parent=app,
        )
        return
    saved = open_profile_editor(app, services, path)
    if saved and Path(saved).exists():
        try:
            summary = summary_from_profile_file(Path(saved))
            app._apply_profile_summary(summary, Path(saved), source="Profil-Editor")
        except Exception:
            pass


def choose_local_firmware(app: Any, services: Any) -> None:
    from tkinter import filedialog

    from local_firmware import prepare_local_bundle

    filename = filedialog.askopenfilename(
        parent=app,
        title="JARNSEN-MESH Firmware-Datei vom PC auswählen",
        filetypes=[
            ("JARNSEN-MESH Artifact", "*.zip *.bin *.uf2 *.txt"),
            ("ZIP-Artifact", "*.zip"),
            ("Firmware", "*.bin *.uf2"),
            ("Alle Dateien", "*.*"),
        ],
    )
    if not filename:
        return
    try:
        expected = app._selected_board_key()
        clearer = getattr(services, "clear_unified_firmware_source", None)
        if callable(clearer) and expected in services.BOARD_PROFILES:
            clearer(expected)
        _invalidate_firmware_status_cache(services, expected or "")
        bundle = prepare_local_bundle(services, Path(filename), expected)
        services._jarnsen_local_firmware_bundle = bundle
        app.bundle = bundle
        app.firmware_var.set(f"{bundle.display_name} · PC-Datei: {Path(filename).name}")
        app._append_log(
            f"FIRMWAREQUELLE · PC-Datei · {filename} · Board={services.BOARD_PROFILES[bundle.board_key]['label']}"
        )
        app._set_status(f"Lokale Firmware bereit · {Path(filename).name}")
        refresh = getattr(app, "refresh_firmware_status", None)
        if callable(refresh):
            app.after(100, refresh)
    except Exception as exc:
        app._show_error(exc)


def check_github_firmware(app: Any, services: Any) -> None:
    services._jarnsen_local_firmware_bundle = None
    board_key = app._selected_board_key()
    clearer = getattr(services, "clear_unified_firmware_source", None)
    if callable(clearer) and board_key in services.BOARD_PROFILES:
        clearer(board_key)
        _invalidate_firmware_status_cache(services, board_key)
    app.bundle = None
    app._append_log("FIRMWAREQUELLE · GitHub · automatische neueste Auswahl")
    app.check_firmware()
    refresh = getattr(app, "refresh_firmware_status", None)
    if callable(refresh):
        app.after(250, lambda: refresh(force=True))


def read_node_info(app: Any, services: Any) -> None:
    if getattr(app, "busy", False):
        return
    device = app._selected_device()
    if device is None:
        messagebox.showwarning(
            "Kein Gerät", "Bitte zuerst ein USB-Gerät auswählen.", parent=app
        )
        return

    refresh_connected_node_state(app, services, show_details=True)


def restart_node(app: Any, services: Any) -> None:
    if getattr(app, "busy", False):
        return
    device = app._selected_device()
    if device is None:
        messagebox.showwarning(
            "Kein Gerät", "Bitte zuerst ein USB-Gerät auswählen.", parent=app
        )
        return
    if not messagebox.askyesno(
        "Node neu starten", f"{device.port} jetzt neu starten?", parent=app
    ):
        return
    app._set_busy(True)

    def worker() -> None:
        try:
            app._set_progress(0.15, "Node neu starten")
            services.reboot_node(device.port)
            app._set_progress(0.55, "Auf USB-Neuanmeldung warten")
            services.wait_for_serial(device.port, timeout=90)
            app._set_progress(1.0, "Node wieder erreichbar")
        except Exception as exc:
            app._show_error(exc)
        finally:
            app._set_busy(False)

    threading.Thread(target=worker, name="jarnsen-node-restart", daemon=True).start()


def start_usb_log(app: Any, services: Any) -> None:
    from usb_log_download import download_tracker_usb_log

    if getattr(app, "busy", False):
        return
    device = app._selected_device()
    if device is None:
        messagebox.showwarning(
            "Kein Gerät", "Bitte zuerst ein USB-Gerät auswählen.", parent=app
        )
        return
    board_key = app._selected_board_key()
    if board_key != "tracker":
        label = services.BOARD_PROFILES.get(board_key or "", {}).get(
            "label", "Unbekannt"
        )
        messagebox.showinfo(
            "USB-Log noch nicht aktiv",
            "Der direkte JARNSEN USB-Logservice ist derzeit für den Tracker V1.1 aktiviert.\n\n"
            f"Ausgewählt: {label}",
            parent=app,
        )
        return

    app._set_busy(True)

    def worker() -> None:
        try:
            app._append_log(
                f"USB-LOG START · Port={device.port} · Protokoll=JARNSEN_TOOL_FULL · Bestätigung am Node=nicht erforderlich"
            )
            app._set_progress(0.02, "USB-Log · Raw-Modus vorbereiten")
            try:
                services.reboot_node(device.port)
            except Exception as exc:
                app._append_log(f"USB-LOG · Reboot meldet {type(exc).__name__}: {exc}")
            app._set_progress(0.08, "USB-Log · Auf USB-Neuanmeldung warten")
            services.wait_for_serial(device.port, timeout=90)
            time.sleep(1.0)
            output_dir = Path(services.PATHS.logs) / "NODE-LOGS"

            def progress(value: float, detail: str) -> None:
                app._set_progress(0.10 + 0.88 * max(0.0, min(1.0, value)), detail)

            target = download_tracker_usb_log(
                device.port,
                output_dir,
                progress=progress,
                log=app._append_log,
            )
            app._set_progress(1.0, f"USB-Log gespeichert · {target.name}")
            app.after(
                0,
                messagebox.showinfo,
                "Node-Log gespeichert",
                f"Der Diagnose-Log wurde übertragen.\n\n{target}",
            )
        except Exception as exc:
            app._append_log(f"USB-LOG FEHLER · {type(exc).__name__}: {exc}")
            app._show_error(exc)
        finally:
            app._set_busy(False)

    threading.Thread(target=worker, name="jarnsen-usb-log", daemon=True).start()


def start_profile_only(app: Any, services: Any) -> None:
    if getattr(app, "busy", False):
        return
    device = app._selected_device()
    if device is None:
        messagebox.showwarning(
            "Kein Gerät", "Bitte zuerst ein Zielgerät per USB auswählen.", parent=app
        )
        return
    board_key = app._selected_board_key()
    if not board_key:
        messagebox.showwarning(
            "Board unbekannt",
            "Bitte das Board auswählen oder automatisch erkennen lassen.",
            parent=app,
        )
        return
    active_profile = Path(services.PATHS.active_profile)
    if not active_profile.exists():
        messagebox.showwarning(
            "Kein Profil",
            "Bitte zuerst ein Profil auswählen oder vom Master einlesen.",
            parent=app,
        )
        return

    try:
        from functional_profiles import active_profile as active_functional_profile
        from functional_profiles import require_compatible_board

        functional = active_functional_profile(services)
        if functional is not None:
            require_compatible_board(functional, board_key, services)
        elif getattr(services, "_jarnsen_functional_profiles_installed", False):
            messagebox.showwarning(
                "Funktionsprofil auswählen",
                "Bitte zuerst auswählen, als was dieses Board arbeiten soll. "
                "Nur die vier Funktionsprofile werden geschrieben.",
                parent=app,
            )
            return
        else:
            from profile_catalog import board_for_profile

            assigned = board_for_profile(active_profile)
            if assigned and assigned != board_key:
                messagebox.showerror(
                    "Profil passt nicht zum Board",
                    f"Das Profil ist {services.BOARD_PROFILES[assigned]['label']} zugeordnet, "
                    f"Zielgerät ist {services.BOARD_PROFILES[board_key]['label']}.",
                    parent=app,
                )
                return
    except Exception as exc:
        app._show_error(exc)
        return

    long_name = str(app.long_name_var.get()).strip()
    short_name = str(app.short_name_var.get()).strip()
    if bool(long_name) != bool(short_name):
        messagebox.showwarning(
            "Gerätename unvollständig",
            "Long Name und Short Name müssen beide gesetzt oder beide leer sein.",
            parent=app,
        )
        return
    if short_name and not (1 <= len(short_name) <= 4):
        messagebox.showwarning(
            "Short Name", "Short Name muss 1 bis 4 Zeichen lang sein.", parent=app
        )
        return

    board_label = services.BOARD_PROFILES[board_key]["label"]
    if not messagebox.askyesno(
        "Nur Profil schreiben",
        f"Port: {device.port}\nBoard: {board_label}\nProfil: {active_profile.name}\n\n"
        "Firmware und Flash-Image werden nicht verändert.\n\nProfil jetzt schreiben?",
        parent=app,
    ):
        return

    app._set_busy(True)

    def worker() -> None:
        previous = getattr(services, "_jarnsen_profile_progress_callback", None)
        try:

            def profile_progress(fraction: float, stage: str, detail: str = "") -> None:
                suffix = f" · {detail}" if detail else ""
                app._set_progress(
                    0.15 + 0.58 * max(0.0, min(1.0, fraction)),
                    f"Nur Profil · {stage}{suffix}",
                )

            services._jarnsen_profile_progress_callback = profile_progress
            app._set_progress(0.05, "Nur Profil · USB/Board prüfen")
            try:
                info = services.verify_node(device.port)
                detected = services.detect_board_from_text(info)
                if detected and detected != board_key:
                    raise services.FlasherError(
                        f"Boardprüfung: erwartet {board_label}, erkannt {services.BOARD_PROFILES[detected]['label']}."
                    )
            except Exception as exc:
                app._append_log(
                    f"PROFIL-ONLY BOARD CHECK · {type(exc).__name__}: {exc}"
                )
                if isinstance(exc, services.FlasherError):
                    raise

            app._set_progress(0.15, "Nur Profil · Grundeinstellungen schreiben")
            prepare = getattr(services, "prepare_profile_write", None)
            if callable(prepare):
                prepare(device.port, long_name, short_name)
            services.restore_profile(device.port)
            if long_name and short_name:
                app._set_progress(0.76, "Nur Profil · Namen schreiben")
                services.set_names(device.port, long_name, short_name)
            app._set_progress(0.84, "Nur Profil · Node neu starten")
            services.reboot_node(device.port)
            app._set_progress(0.91, "Nur Profil · Auf Node warten")
            services.wait_for_serial(device.port, timeout=90)
            app._set_progress(0.96, "Nur Profil · Endprüfung")
            services.verify_node(device.port, expected_board=board_key)
            app._set_progress(0.98, "Nur Profil · Profilwerte vergleichen")
            services.verify_written_profile(
                device.port, active_profile, board_key=board_key
            )
            app._set_progress(1.0, "Nur Profil · Fertig")
            app.after(
                0,
                messagebox.showinfo,
                "Profil erfolgreich geschrieben",
                f"{board_label} wurde ohne Firmware-Flash konfiguriert.",
            )
        except Exception as exc:
            app._append_log(f"PROFIL-ONLY FEHLER · {type(exc).__name__}: {exc}")
            app._show_error(exc)
        finally:
            services._jarnsen_profile_progress_callback = previous
            app._set_busy(False)

    threading.Thread(
        target=worker, name="jarnsen-profile-only-native", daemon=True
    ).start()


def start_firmware_only(app: Any, services: Any) -> None:
    from flash_runtime import _stream_esptool

    if getattr(app, "busy", False):
        return
    device = app._selected_device()
    if device is None:
        messagebox.showwarning(
            "Kein Gerät", "Bitte zuerst ein USB-Gerät auswählen.", parent=app
        )
        return
    board_key = app._selected_board_key()
    # JARNSEN_V3_FIRMWARE_UPDATE_FAIL_CLOSED_V1
    # This legacy entry point must not bypass the service-level safety gate.
    if board_key == "repeater":
        messagebox.showwarning(
            "V3-Update gesperrt",
            "Nach App-Slot-Updates mit Builds 453/465 trat ein Bootloop auf. "
            "Ein Erstflash startete dagegen. Bis die Ursache und eine "
            "sichere Migration bestätigt sind, ist 'Nur Firmware updaten' "
            "für den Heltec V3 gesperrt. Es wird nichts geschrieben.",
            parent=app,
        )
        return
    if board_key not in {"tracker", "repeater"}:
        messagebox.showinfo(
            "Firmware-Update",
            "Der reine Firmware-Updatepfad ist aktuell für Tracker V1.1 und Heltec V3 freigegeben.",
            parent=app,
        )
        return
    app._set_busy(True)

    def worker() -> None:
        previous = getattr(services, "_jarnsen_flash_progress_callback", None)
        try:
            board_label = services.BOARD_PROFILES[board_key]["label"]
            app._set_progress(0.03, "Firmware-Update · Firmware auflösen")
            bundle = getattr(app, "bundle", None)
            if not (
                bundle is not None and getattr(bundle, "board_key", None) == board_key
            ):
                bundle = services.GitHubFirmwareClient().resolve_latest(board_key)
                app.bundle = bundle
                app.after(0, app.firmware_var.set, bundle.display_name)

            preflight = getattr(services, "run_flash_preflight", None)
            if callable(preflight):
                report = preflight(device.port, board_key, bundle, "update")
                for line in report.format().splitlines():
                    if line:
                        app._append_log(f"PREFLIGHT · {line}")
                if not report.ready:
                    raise services.FlasherError(report.format())

            identity = None
            cached_identity = getattr(services, "cached_jarnsen_identity", None)
            if callable(cached_identity):
                identity = cached_identity(device.port)
            if identity is None:
                query_identity = getattr(services, "query_jarnsen_identity", None)
                if callable(query_identity):
                    identity = query_identity(device.port)
            if identity is None or not bool(getattr(identity, "is_jarnsen", False)):
                raise services.FlasherError(
                    "Das reine Firmware-Update ist nur für ein bereits eingerichtetes JARNSEN-MESH-Gerät sicher. "
                    "Für ein neues oder VANILLA-Gerät bitte oben ein Funktionsprofil wählen und „Erstflash“ verwenden."
                )

            update_image = Path(bundle.update)
            if not update_image.exists():
                raise services.FlasherError(f"Update-Image fehlt: {update_image}")

            decision: list[bool] = []
            ready = threading.Event()

            def ask() -> None:
                try:
                    decision.append(
                        messagebox.askyesno(
                            "Nur Firmware updaten",
                            f"Port: {device.port}\nBoard: {board_label}\nFirmware: {bundle.display_name}\n\n"
                            "Nur die App-Firmware-Slots werden aktualisiert. Profil, Namen, NVS und Logs bleiben erhalten."
                            + (
                                "\n\nACHTUNG: Diese Firmware wurde bewusst manuell ausgewählt. "
                                "Wenn sie älter als die installierte Version ist, wird ein Downgrade durchgeführt."
                                if bool(getattr(bundle, "allow_downgrade", False))
                                else ""
                            )
                            + "\n\nFirmware jetzt aktualisieren?",
                            parent=app,
                        )
                    )
                finally:
                    ready.set()

            app.after(0, ask)
            ready.wait()
            if not decision or not decision[0]:
                app._set_progress(0.0, "Firmware-Update abgebrochen")
                return

            baud = str(getattr(services, "_jarnsen_flash_baud", "921600"))
            if baud not in {"115200", "230400", "460800", "921600"}:
                baud = "921600"

            def flash_progress(fraction: float, stage: str, detail: str) -> None:
                suffix = f" · {detail}" if detail else ""
                app._set_progress(fraction, f"Firmware-Update · {stage}{suffix}")

            services._jarnsen_flash_progress_callback = flash_progress
            common = [
                "--baud",
                baud,
                "write-flash",
                "--flash-mode",
                "dio",
                "--flash-freq",
                "80m",
                "--flash-size",
                "keep",
            ]
            _stream_esptool(
                services,
                device.port,
                [*common, "0x10000", str(update_image)],
                timeout=600,
                stage="App-Slot A schreiben",
                phase_start=0.08,
                phase_end=0.48,
                log=app._append_log,
            )
            _stream_esptool(
                services,
                device.port,
                [*common, "0x340000", str(update_image)],
                timeout=600,
                stage="App-Slot B schreiben",
                phase_start=0.48,
                phase_end=0.88,
                log=app._append_log,
            )
            _stream_esptool(
                services,
                device.port,
                ["run"],
                timeout=30,
                stage="Node starten",
                phase_start=0.88,
                phase_end=0.91,
                log=app._append_log,
                check=False,
            )
            app._set_progress(0.93, "Firmware-Update · Auf USB warten")
            services.wait_for_serial(device.port, timeout=90)
            app._set_progress(0.97, "Firmware-Update · Board prüfen")
            services.verify_node(device.port, expected_board=board_key)
            app._set_progress(1.0, "Firmware-Update fertig")
            app.after(
                0,
                messagebox.showinfo,
                "Firmware aktualisiert",
                f"{bundle.display_name}\n\nProfil, Namen, NVS und Diagnose-Logs wurden nicht verändert.",
            )
        except Exception as exc:
            app._append_log(f"FIRMWARE-ONLY FEHLER · {type(exc).__name__}: {exc}")
            app._show_error(exc)
        finally:
            services._jarnsen_flash_progress_callback = previous
            app._set_busy(False)

    threading.Thread(
        target=worker, name="jarnsen-firmware-only-native", daemon=True
    ).start()
