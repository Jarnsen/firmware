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


def _safe_start_firmware_only(app: Any, services: Any) -> None:
    """Run firmware-only update without opening a Tk modal from a worker thread."""
    from unified_service_v2 import flash_firmware_only_bundle

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
    if board_key not in services.BOARD_PROFILES:
        messagebox.showwarning(
            "Board unbekannt",
            "Bitte das Board zuerst eindeutig erkennen oder manuell auswählen.",
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

            report = services.run_flash_preflight(
                device.port, board_key, bundle, "update"
            )
            for line in report.format().splitlines():
                if line:
                    app._append_log(f"PREFLIGHT · {line}")
            if not report.ready:
                raise services.FlasherError(report.format())

            def flash_progress(fraction: float, stage: str, detail: str) -> None:
                suffix = f" · {detail}" if detail else ""
                app._set_progress(
                    fraction,
                    f"Firmware-Update · {stage}{suffix}",
                )

            services._jarnsen_flash_progress_callback = flash_progress
            app._append_log(
                f"FIRMWARE-ONLY FLASH START · Port={device.port} · Board={board_label} · "
                f"Datei={update_image.name}"
            )
            flash_firmware_only_bundle(
                services, device.port, board_key, bundle, app._append_log
            )

            app._set_progress(0.93, "Firmware-Update · Auf USB warten")
            services.wait_for_serial(device.port, timeout=90)
            live_port = services.resolve_live_port(device.port)
            app._set_progress(0.97, "Firmware-Update · Board prüfen")
            services.verify_node(live_port, expected_board=board_key)
            app._append_log(
                f"FIRMWARE-ONLY FLASH ENDE · Port={live_port} · Board={board_label} · "
                f"Firmware={bundle.display_name} · verifiziert=1"
            )
            app._set_progress(1.0, "Firmware-Update fertig · Board verifiziert")

            artifact_kind = str(
                services.BOARD_PROFILES[board_key].get("artifact_kind") or "esp32"
            ).lower()
            if artifact_kind == "uf2":
                write_summary = "• UF2-Firmware übertragen und verifiziert\n"
            else:
                target_count = len(getattr(bundle, "flash_targets", []) or ())
                partition_word = "Partition" if target_count == 1 else "Partitionen"
                write_summary = (
                    f"• {target_count or 'Alle'} Anwendungs-{partition_word} in einem "
                    "Flashvorgang geschrieben und verifiziert\n"
                )
            completion_text = (
                f"{board_label} wurde erfolgreich aktualisiert.\n\n"
                f"Port: {live_port}\n"
                f"Firmware: {bundle.display_name}\n\n"
                "Durchgeführt:\n"
                f"{write_summary}"
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
                f"FIRMWARE-ONLY ABSCHLUSS-POPUP · Port={live_port} · "
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
            app._append_log(f"FIRMWARE-ONLY FEHLER · {type(exc).__name__}: {exc}")
            app._show_error(exc)
        finally:
            services._jarnsen_flash_progress_callback = previous
            app._set_busy(False)

    threading.Thread(
        target=worker,
        name="jarnsen-firmware-only-native-safe",
        daemon=True,
    ).start()


_safe_start_firmware_only._jarnsen_all_board_dynamic_update = True


def _install_centered_progress_patch() -> None:
    """Render the percentage as true canvas text over one continuous progress bar."""
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
        border_attempts = {"count": 0}

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
                progress.configure(height=18, corner_radius=9)
                progress.pack_configure(side="left", fill="x", expand=True)

                # The original percentage label must not occupy space beside the
                # bar and must not be placed on top of it: even a "transparent"
                # CTkLabel paints its parent background and therefore creates the
                # visible hole/capsule. Hide it completely and draw only text on
                # the progress bar's own canvas.
                percent_label.pack_forget()
                try:
                    percent_label.place_forget()
                except Exception:
                    pass

                canvas = getattr(progress, "_canvas", None)
                if canvas is None:
                    raise RuntimeError("CTkProgressBar canvas not available")

                old_item = getattr(self, "_jarnsen_progress_canvas_text", None)
                if old_item is not None:
                    try:
                        canvas.delete(old_item)
                    except Exception:
                        pass

                def canvas_center() -> tuple[float, float]:
                    try:
                        width = max(1, int(canvas.winfo_width()))
                        height = max(1, int(canvas.winfo_height()))
                    except Exception:
                        width, height = 1, 18
                    return (width / 2.0, height / 2.0)

                x, y = canvas_center()
                text_item = canvas.create_text(
                    x,
                    y,
                    text="0%",
                    fill="#FFFFFF",
                    font=("Segoe UI", 9, "bold"),
                    anchor="center",
                )
                self._jarnsen_progress_canvas_text = text_item

                def update_overlay(value: float) -> None:
                    try:
                        fraction = max(0.0, min(1.0, float(value)))
                        started = getattr(self, "_jarnsen_flash_started_at", None)
                        if started is not None and getattr(self, "busy", False):
                            elapsed = max(0, int(time.monotonic() - float(started)))
                        else:
                            elapsed = max(
                                0, int(getattr(self, "_jarnsen_flash_elapsed", 0) or 0)
                            )
                        hours, remainder = divmod(elapsed, 3600)
                        minutes, seconds = divmod(remainder, 60)
                        clock = (
                            f"{hours:d}:{minutes:02d}:{seconds:02d}"
                            if hours
                            else f"{minutes:02d}:{seconds:02d}"
                        )
                        label = f"{int(round(fraction * 100))}%"
                        if started is not None or elapsed:
                            label += f" ({clock})"
                        cx, cy = canvas_center()
                        canvas.coords(text_item, cx, cy)
                        canvas.itemconfigure(
                            text_item,
                            text=label,
                            fill="#FFFFFF",
                        )
                        canvas.tag_raise(text_item)
                    except Exception:
                        pass

                def reposition_overlay(_event: Any = None) -> None:
                    try:
                        cx, cy = canvas_center()
                        canvas.coords(text_item, cx, cy)
                        canvas.tag_raise(text_item)
                    except Exception:
                        pass

                try:
                    canvas.bind("<Configure>", reposition_overlay, add="+")
                except Exception:
                    pass

                current_set_progress = getattr(self, "_set_progress", None)
                if callable(current_set_progress) and not getattr(
                    self, "_jarnsen_progress_overlay_wrapped", False
                ):

                    def centered_set_progress(
                        value: float,
                        text: str,
                        _base=current_set_progress,
                    ):
                        result = _base(value, text)
                        try:
                            self.after(0, update_overlay, value)
                        except Exception:
                            pass
                        return result

                    self._set_progress = centered_set_progress
                    self._jarnsen_progress_overlay_wrapped = True

                try:
                    update_overlay(float(progress.get()))
                except Exception:
                    update_overlay(0.0)

                if not getattr(self, "_jarnsen_progress_elapsed_tick", False):
                    self._jarnsen_progress_elapsed_tick = True

                    def elapsed_tick() -> None:
                        try:
                            if getattr(self, "busy", False):
                                update_overlay(float(progress.get()))
                            self.after(1000, elapsed_tick)
                        except Exception:
                            pass

                    self.after(1000, elapsed_tick)

                self._jarnsen_progress_centered = True
                _emit(
                    "PROGRESS LAYOUT centered=1 full-width=1 percent-outside=0 "
                    "continuous-bar=1 canvas-text-overlay=1 badge=0 height=18"
                )
            except Exception as exc:
                _emit(
                    "PROGRESS CENTER PATCH failed "
                    f"type={type(exc).__name__} message={exc}"
                )

        def repair_firmware_status_border() -> None:
            """Overlay the bottom status border so child widgets cannot cover it."""
            border_attempts["count"] += 1
            target = None

            def walk(widget: Any):
                yield widget
                try:
                    children = widget.winfo_children()
                except Exception:
                    children = []
                for child in children:
                    yield from walk(child)

            try:
                for widget in walk(self):
                    if not isinstance(widget, ctk.CTkFrame):
                        continue
                    labels: set[str] = set()
                    try:
                        for child in widget.winfo_children():
                            if not isinstance(child, ctk.CTkLabel):
                                continue
                            text = str(child.cget("text") or "").strip()
                            if text:
                                labels.add(text)
                    except Exception:
                        continue
                    if (
                        "Installierte Firmware:" in labels
                        and "Verfügbare Firmware:" in labels
                    ):
                        target = widget
                        break
            except Exception:
                target = None

            if target is None:
                if border_attempts["count"] < 30:
                    try:
                        self.after(100, repair_firmware_status_border)
                    except Exception:
                        pass
                return

            try:
                line = getattr(self, "_jarnsen_firmware_status_bottom_border", None)
                if line is None or not int(line.winfo_exists()):
                    line = ctk.CTkFrame(
                        target,
                        height=2,
                        corner_radius=0,
                        fg_color=target.cget("border_color"),
                    )
                    self._jarnsen_firmware_status_bottom_border = line

                def sync_border() -> None:
                    try:
                        if not int(target.winfo_exists()) or not int(
                            line.winfo_exists()
                        ):
                            return
                        line.configure(fg_color=target.cget("border_color"))
                        line.place(relx=0.004, rely=1.0, y=-2, relwidth=0.992, height=2)
                        line.lift()
                        self.after(180, sync_border)
                    except Exception:
                        return

                sync_border()
                _emit("FIRMWARE STATUS BORDER repaired bottom-overlay=1 color-sync=1")
            except Exception as exc:
                _emit(
                    "FIRMWARE STATUS BORDER repair failed "
                    f"type={type(exc).__name__} message={exc}"
                )

        try:
            self.after(360, apply_layout)
            self.after(420, repair_firmware_status_border)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init
    ctk.CTk._jarnsen_progress_center_patch = True
    _emit(
        "PROGRESS CENTER PATCH installed retry-window=2s "
        "continuous-bar=1 canvas-text-overlay=1 badge=0"
    )


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
        "continuous-bar=1 canvas-text-overlay=1 badge=0 "
        "firmware-border-repair=1 main-thread=1 "
        f"bindings={patched!r}"
    )
