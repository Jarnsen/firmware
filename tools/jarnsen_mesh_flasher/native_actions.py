from __future__ import annotations

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


def choose_profile(app: Any, services: Any) -> None:
    from profile_editor import enhanced_select_profile_dialog
    from profile_utils import summary_from_profile_file

    board_key = app._selected_board_key() if hasattr(app, "_selected_board_key") else None
    selected = enhanced_select_profile_dialog(
        app,
        services,
        board_key=board_key,
        title="JARNSEN MESH · Profil auswählen",
    )
    if not selected:
        return
    try:
        path = services.import_profile_file(Path(selected))
        summary = summary_from_profile_file(path)
        app._apply_profile_summary(summary, path, source="Profil")
        app._set_status(
            f"Profil geladen · {summary.long_name or path.name} · Rolle {summary.role or 'unbekannt'}"
        )
    except Exception as exc:
        app._show_error(exc)


def edit_current_profile(app: Any, services: Any) -> None:
    from profile_editor import open_profile_editor
    from profile_utils import summary_from_profile_file

    raw = str(app.profile_path_var.get() or "").strip()
    path = Path(raw) if raw and raw != "Kein Profil geladen" else Path(services.PATHS.active_profile)
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
    app.bundle = None
    app._append_log("FIRMWAREQUELLE · GitHub · lokale Auswahl verworfen")
    app.check_firmware()
    refresh = getattr(app, "refresh_firmware_status", None)
    if callable(refresh):
        app.after(250, lambda: refresh(force=True))


def read_node_info(app: Any, services: Any) -> None:
    if getattr(app, "busy", False):
        return
    device = app._selected_device()
    if device is None:
        messagebox.showwarning("Kein Gerät", "Bitte zuerst ein USB-Gerät auswählen.", parent=app)
        return

    app._set_busy(True)
    app._set_status(f"Node-Info von {device.port} lesen …")

    def worker() -> None:
        try:
            info = services.verify_node(device.port)
            detected = services.detect_board_from_text(info)
            app._append_log(f"NODE-INFO · Port={device.port} · Board={detected or 'unbekannt'}")
            shown = info.strip()
            if len(shown) > 5000:
                shown = shown[:5000] + "\n…"
            app.after(0, messagebox.showinfo, "Node-Info", shown or "Keine Info empfangen.")
            app._set_status("Node-Info gelesen")
        except Exception as exc:
            app._show_error(exc)
        finally:
            app._set_busy(False)

    threading.Thread(target=worker, name="jarnsen-node-info", daemon=True).start()


def restart_node(app: Any, services: Any) -> None:
    if getattr(app, "busy", False):
        return
    device = app._selected_device()
    if device is None:
        messagebox.showwarning("Kein Gerät", "Bitte zuerst ein USB-Gerät auswählen.", parent=app)
        return
    if not messagebox.askyesno("Node neu starten", f"{device.port} jetzt neu starten?", parent=app):
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
        messagebox.showwarning("Kein Gerät", "Bitte zuerst ein USB-Gerät auswählen.", parent=app)
        return
    board_key = app._selected_board_key()
    if board_key != "tracker":
        label = services.BOARD_PROFILES.get(board_key or "", {}).get("label", "Unbekannt")
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
        messagebox.showwarning("Kein Gerät", "Bitte zuerst ein Zielgerät per USB auswählen.", parent=app)
        return
    board_key = app._selected_board_key()
    if not board_key:
        messagebox.showwarning("Board unbekannt", "Bitte das Board auswählen oder automatisch erkennen lassen.", parent=app)
        return
    active_profile = Path(services.PATHS.active_profile)
    if not active_profile.exists():
        messagebox.showwarning("Kein Profil", "Bitte zuerst ein Profil auswählen oder vom Master einlesen.", parent=app)
        return

    try:
        from profile_catalog import board_for_profile
        assigned = board_for_profile(active_profile)
    except Exception:
        assigned = None
    if assigned and assigned != board_key:
        messagebox.showerror(
            "Profil passt nicht zum Board",
            f"Das Profil ist {services.BOARD_PROFILES[assigned]['label']} zugeordnet, "
            f"Zielgerät ist {services.BOARD_PROFILES[board_key]['label']}.",
            parent=app,
        )
        return

    long_name = str(app.long_name_var.get()).strip()
    short_name = str(app.short_name_var.get()).strip()
    if bool(long_name) != bool(short_name):
        messagebox.showwarning("Gerätename unvollständig", "Long Name und Short Name müssen beide gesetzt oder beide leer sein.", parent=app)
        return
    if short_name and not (1 <= len(short_name) <= 4):
        messagebox.showwarning("Short Name", "Short Name muss 1 bis 4 Zeichen lang sein.", parent=app)
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
                app._set_progress(0.15 + 0.58 * max(0.0, min(1.0, fraction)), f"Nur Profil · {stage}{suffix}")

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
                app._append_log(f"PROFIL-ONLY BOARD CHECK · {type(exc).__name__}: {exc}")
                if isinstance(exc, services.FlasherError):
                    raise

            app._set_progress(0.15, "Nur Profil · Grundeinstellungen schreiben")
            services.restore_profile(device.port)
            if long_name and short_name:
                app._set_progress(0.76, "Nur Profil · Namen schreiben")
                services.set_names(device.port, long_name, short_name)
            app._set_progress(0.84, "Nur Profil · Node neu starten")
            services.reboot_node(device.port)
            app._set_progress(0.91, "Nur Profil · Auf Node warten")
            services.wait_for_serial(device.port, timeout=90)
            app._set_progress(0.97, "Nur Profil · Endprüfung")
            services.verify_node(device.port, expected_board=board_key)
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

    threading.Thread(target=worker, name="jarnsen-profile-only-native", daemon=True).start()


def start_firmware_only(app: Any, services: Any) -> None:
    from flash_runtime import _stream_esptool

    if getattr(app, "busy", False):
        return
    device = app._selected_device()
    if device is None:
        messagebox.showwarning("Kein Gerät", "Bitte zuerst ein USB-Gerät auswählen.", parent=app)
        return
    board_key = app._selected_board_key()
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
            if not (bundle is not None and getattr(bundle, "board_key", None) == board_key):
                bundle = services.GitHubFirmwareClient().resolve_latest(board_key)
                app.bundle = bundle
                app.after(0, app.firmware_var.set, bundle.display_name)

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
                            "Nur die App-Firmware-Slots werden aktualisiert. Profil, Namen, NVS und Logs bleiben erhalten.\n\n"
                            "Firmware jetzt aktualisieren?",
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
                "--baud", baud, "write-flash", "--flash-mode", "dio",
                "--flash-freq", "80m", "--flash-size", "keep",
            ]
            _stream_esptool(
                services, device.port, [*common, "0x10000", str(update_image)],
                timeout=600, stage="App-Slot A schreiben", phase_start=0.08, phase_end=0.48,
                log=app._append_log,
            )
            _stream_esptool(
                services, device.port, [*common, "0x340000", str(update_image)],
                timeout=600, stage="App-Slot B schreiben", phase_start=0.48, phase_end=0.88,
                log=app._append_log,
            )
            _stream_esptool(
                services, device.port, ["run"], timeout=30, stage="Node starten",
                phase_start=0.88, phase_end=0.91, log=app._append_log, check=False,
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

    threading.Thread(target=worker, name="jarnsen-firmware-only-native", daemon=True).start()
