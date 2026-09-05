from __future__ import annotations

import threading
from pathlib import Path
from tkinter import messagebox
from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _safe_start_firmware_only(app: Any, services: Any) -> None:
    """Run firmware-only update without opening a Tk modal from a worker thread."""
    from flash_runtime import _stream_esptool

    if getattr(app, "busy", False):
        return

    device = app._selected_device()
    if device is None:
        messagebox.showwarning(
            "Kein Gerät",
            "Bitte zuerst ein USB-Gerät auswählen.",
            parent=app,
        )
        return

    board_key = app._selected_board_key()
    if board_key not in {"tracker", "repeater"}:
        messagebox.showinfo(
            "Firmware-Update",
            "Der reine Firmware-Updatepfad ist aktuell für Tracker V1.1 und Heltec V3 freigegeben.\n\n"
            "Die übrigen Unified-Core-Boards können über AUTOMATISCH FLASHEN vollständig geflasht werden.",
            parent=app,
        )
        return

    board_label = str(services.BOARD_PROFILES[board_key]["label"])
    cached = getattr(app, "bundle", None)
    if cached is not None and getattr(cached, "board_key", None) == board_key:
        firmware_text = str(cached.display_name)
    else:
        cached = None
        firmware_text = "Neueste erfolgreiche JARNSEN-MESH Firmware von GitHub"

    # IMPORTANT: this modal must run directly on the Tk main thread. The old
    # implementation created it from a background worker via app.after() and
    # then blocked that worker on an Event. In the frozen borderless Windows
    # build this was the exact transition where the process could disappear.
    approved = messagebox.askyesno(
        "Nur Firmware updaten",
        f"Port: {device.port}\n"
        f"Board: {board_label}\n"
        f"Firmware: {firmware_text}\n\n"
        "Nur die App-Firmware-Slots werden aktualisiert. Profil, Namen, NVS und Logs bleiben erhalten.\n\n"
        "Firmware jetzt aktualisieren?",
        parent=app,
    )
    if not approved:
        app._append_log(
            f"FIRMWARE-ONLY ABBRUCH · Port={device.port} · Board={board_label} · vor Flash"
        )
        app._set_progress(0.0, "Firmware-Update abgebrochen")
        return

    app._append_log(
        f"FIRMWARE-ONLY FREIGABE · Port={device.port} · Board={board_label} · "
        f"Quelle={'Cache' if cached is not None else 'GitHub'}"
    )
    _emit(
        f"FIRMWARE-ONLY MAIN-THREAD CONFIRM OK port={device.port!r} board={board_key!r}"
    )
    app._set_busy(True)

    def worker() -> None:
        previous = getattr(services, "_jarnsen_flash_progress_callback", None)
        try:
            app._set_progress(0.03, "Firmware-Update · Firmware auflösen")
            app._append_log(
                f"FIRMWARE-ONLY RESOLVE START · Port={device.port} · Board={board_label}"
            )

            bundle = cached
            if bundle is None:
                bundle = services.GitHubFirmwareClient().resolve_latest(board_key)
                app.bundle = bundle
                app.after(0, app.firmware_var.set, bundle.display_name)

            update_image = Path(bundle.update)
            if not update_image.exists():
                raise services.FlasherError(f"Update-Image fehlt: {update_image}")

            app._append_log(
                f"FIRMWARE-ONLY RESOLVE ENDE · {bundle.display_name} · "
                f"Datei={update_image.name} · Bytes={update_image.stat().st_size}"
            )

            baud = str(getattr(services, "_jarnsen_flash_baud", "921600"))
            if baud not in {"115200", "230400", "460800", "921600"}:
                baud = "921600"

            def flash_progress(fraction: float, stage: str, detail: str) -> None:
                suffix = f" · {detail}" if detail else ""
                app._set_progress(
                    fraction,
                    f"Firmware-Update · {stage}{suffix}",
                )

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

            app._append_log(
                f"FIRMWARE-ONLY FLASH START · Port={device.port} · Board={board_label} · "
                f"Baud={baud} · Datei={update_image.name}"
            )
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
            app._append_log(
                f"FIRMWARE-ONLY FLASH ENDE · Port={device.port} · Board={board_label} · "
                f"Firmware={bundle.display_name} · verifiziert=1"
            )
            app._set_progress(1.0, "Firmware-Update fertig · Board verifiziert")

            completion_text = (
                f"{board_label} wurde erfolgreich aktualisiert.\n\n"
                f"Port: {device.port}\n"
                f"Firmware: {bundle.display_name}\n\n"
                "Durchgeführt:\n"
                "• App-Slot A geschrieben und verifiziert\n"
                "• App-Slot B geschrieben und verifiziert\n"
                "• Node neu gestartet\n"
                "• USB-Verbindung wiederhergestellt\n"
                f"• Board als {board_label} verifiziert\n\n"
                "Unverändert geblieben:\n"
                "• Profil / Grundeinstellungen\n"
                "• Long Name und Short Name\n"
                "• NVS\n"
                "• Diagnose-Logs"
            )
            app._append_log(
                f"FIRMWARE-ONLY ABSCHLUSS-POPUP · Port={device.port} · "
                f"Board={board_label} · Firmware={bundle.display_name}"
            )

            def show_completion() -> None:
                try:
                    app.lift()
                    app.focus_force()
                except Exception:
                    pass
                messagebox.showinfo(
                    "Firmware-Update abgeschlossen",
                    completion_text,
                    parent=app,
                )

            # Schedule the result dialog on Tk's main thread. Never open a Tk
            # modal directly from the flash worker.
            app.after(0, show_completion)
        except Exception as exc:
            app._append_log(
                f"FIRMWARE-ONLY FEHLER · {type(exc).__name__}: {exc}"
            )
            app._show_error(exc)
        finally:
            services._jarnsen_flash_progress_callback = previous
            app._set_busy(False)

    threading.Thread(
        target=worker,
        name="jarnsen-firmware-only-native-safe",
        daemon=True,
    ).start()


def _install_centered_progress_patch() -> None:
    """Center the percentage inside the full-width automatic progress bar."""
    try:
        import customtkinter as ctk
    except Exception as exc:
        _emit(
            "PROGRESS CENTER PATCH unavailable "
            f"type={type(exc).__name__} message={exc}"
        )
        return

    if getattr(ctk.CTk, "_jarnsen_progress_center_patch", False):
        return

    previous_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        previous_root_init(self, *args, **kwargs)
        attempts = {"count": 0}

        def apply_layout() -> None:
            attempts["count"] += 1
            progress = getattr(self, "progress", None)
            if progress is None:
                if attempts["count"] < 20:
                    try:
                        self.after(100, apply_layout)
                    except Exception:
                        pass
                return

            progress_row = getattr(progress, "master", None)
            if progress_row is None:
                return

            percent_label = None
            try:
                for child in progress_row.winfo_children():
                    if child is progress or not isinstance(child, ctk.CTkLabel):
                        continue
                    try:
                        text = str(child.cget("text") or "").strip()
                    except Exception:
                        text = ""
                    try:
                        textvariable = child.cget("textvariable")
                    except Exception:
                        textvariable = None
                    if text.endswith("%") or textvariable:
                        percent_label = child
                        break
            except Exception:
                percent_label = None

            if percent_label is None:
                if attempts["count"] < 20:
                    try:
                        self.after(100, apply_layout)
                    except Exception:
                        pass
                return

            try:
                fill_color = "#0B72E7"
                track_color = "#294055"
                progress.configure(height=18, corner_radius=9)
                progress.pack_configure(side="left", fill="x", expand=True)

                # Remove the separate right-hand percentage from the pack flow,
                # so the progress bar receives the complete row width. The small
                # centered badge follows the underlying bar color: before 50% it
                # sits on the track, from 50% onward it is surrounded by the blue
                # completed area instead of cutting a dark hole into the bar.
                percent_label.pack_forget()
                percent_label.configure(
                    width=36,
                    height=18,
                    corner_radius=9,
                    anchor="center",
                    text_color="#FFFFFF",
                    fg_color=track_color,
                    font=ctk.CTkFont(size=9, weight="bold"),
                )
                percent_label.place(relx=0.5, rely=0.5, anchor="center")
                percent_label.lift()

                current_set_progress = getattr(self, "_set_progress", None)
                if callable(current_set_progress) and not getattr(
                    self, "_jarnsen_progress_color_wrapped", False
                ):
                    def centered_set_progress(
                        value: float,
                        text: str,
                        _base=current_set_progress,
                        _label=percent_label,
                    ):
                        result = _base(value, text)
                        try:
                            fraction = max(0.0, min(1.0, float(value)))
                            _label.configure(
                                fg_color=fill_color if fraction >= 0.5 else track_color
                            )
                            _label.lift()
                        except Exception:
                            pass
                        return result

                    self._set_progress = centered_set_progress
                    self._jarnsen_progress_color_wrapped = True

                # Synchronize the badge once with the currently displayed value.
                try:
                    fraction = float(progress.get())
                    percent_label.configure(
                        fg_color=fill_color if fraction >= 0.5 else track_color
                    )
                except Exception:
                    pass

                self._jarnsen_progress_centered = True
                _emit(
                    "PROGRESS LAYOUT centered=1 full-width=1 percent-outside=0 "
                    "adaptive-fill-bg=1 height=18"
                )
            except Exception as exc:
                _emit(
                    "PROGRESS CENTER PATCH failed "
                    f"type={type(exc).__name__} message={exc}"
                )

        try:
            self.after(360, apply_layout)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init
    setattr(ctk.CTk, "_jarnsen_progress_center_patch", True)
    _emit("PROGRESS CENTER PATCH installed retry-window=2s adaptive-fill-bg=1")


def install(services: Any) -> None:
    """Replace the firmware-only action and finalize flash-result UI behavior."""
    import native_actions

    native_actions.start_firmware_only = _safe_start_firmware_only

    patched = ["native_actions"]
    try:
        import reference_dashboard

        reference_dashboard.start_firmware_only = _safe_start_firmware_only
        patched.append("reference_dashboard")
    except Exception as exc:
        _emit(
            "FIRMWARE-ONLY STABILITY reference binding skipped "
            f"type={type(exc).__name__} message={exc}"
        )

    _install_centered_progress_patch()

    _emit(
        "FIRMWARE-ONLY STABILITY installed main-thread-confirm=1 "
        "main-thread-completion=1 worker-modal=0 progress-centered=1 "
        "adaptive-fill-bg=1 "
        f"bindings={patched!r}"
    )
