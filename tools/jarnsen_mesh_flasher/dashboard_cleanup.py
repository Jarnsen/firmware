from __future__ import annotations

import os
import re
import sys
import threading
from pathlib import Path
from tkinter import messagebox
from typing import Any

import customtkinter as ctk

from profile_utils import summary_from_info_text


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _walk(widget: Any):
    yield widget
    try:
        children = widget.winfo_children()
    except Exception:
        children = []
    for child in children:
        yield from _walk(child)


def _text(widget: Any) -> str:
    try:
        return str(widget.cget("text") or "")
    except Exception:
        return ""


def _find_card(root: Any, title: str) -> Any | None:
    for widget in _walk(root):
        if _text(widget) == title:
            return getattr(widget, "master", None)
    return None


def _open_folder(path: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", str(path)])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


def install(services: Any) -> None:
    """Polish the Full-HD dashboard without replacing the stable app workflow."""
    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def patch_app() -> None:
            if getattr(self, "_jarnsen_dashboard_cleanup_installed", False):
                return
            required = (
                "body",
                "progress",
                "log_box",
                "log_path",
                "_selected_device",
                "_selected_board_key",
                "_append_log",
                "_set_progress",
                "_set_busy",
            )
            if not all(hasattr(self, name) for name in required):
                try:
                    self.after(200, patch_app)
                except Exception:
                    pass
                return

            device_card = _find_card(self, "1 · GERÄT")
            names_card = _find_card(self, "4 · GERÄTENAME")
            action_card = _find_card(self, "5 · AUTOMATISCHER ABLAUF")
            log_card = _find_card(self, "PROTOKOLL")
            if not all((device_card, names_card, action_card, log_card)):
                try:
                    self.after(250, patch_app)
                except Exception:
                    pass
                return

            self._jarnsen_dashboard_cleanup_installed = True

            # Slightly favor the right operational column and reclaim vertical
            # space from cards that no longer need to show every mode at once.
            try:
                self.body.grid_columnconfigure(0, weight=9, uniform="")
                self.body.grid_columnconfigure(1, weight=10, uniform="")
                self.body.grid_rowconfigure(0, weight=1, minsize=128)
                self.body.grid_rowconfigure(1, weight=1, minsize=150)
                self.body.grid_rowconfigure(2, weight=1, minsize=128)
                self.body.grid_rowconfigure(3, weight=3, minsize=185)
            except Exception:
                pass

            for card in (device_card, names_card, action_card, log_card):
                try:
                    card.configure(corner_radius=14)
                except Exception:
                    pass

            # Rename the name block to make its purpose clearer.
            for child in names_card.winfo_children():
                if _text(child) == "4 · GERÄTENAME":
                    try:
                        child.configure(text="4 · IDENTITÄT")
                    except Exception:
                        pass
                    break

            # --- Device service bar -------------------------------------------------
            service_bar = ctk.CTkFrame(device_card, fg_color="transparent")
            service_bar.pack(fill="x", padx=18, pady=(0, 12))
            ctk.CTkLabel(
                service_bar,
                text="SERVICE",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=("gray40", "gray65"),
            ).pack(side="left", padx=(0, 10))

            original_usb_button = next((w for w in _walk(device_card) if _text(w) == "NODE-LOG USB"), None)
            usb_command = getattr(original_usb_button, "_command", None) if original_usb_button is not None else None
            if original_usb_button is not None:
                try:
                    original_usb_button.pack_forget()
                except Exception:
                    pass

            service_buttons: list[Any] = []
            if callable(usb_command):
                usb_button = ctk.CTkButton(
                    service_bar,
                    text="NODE-LOG USB",
                    width=125,
                    height=30,
                    command=usb_command,
                )
                usb_button.pack(side="left", padx=(0, 8))
                service_buttons.append(usb_button)
                self.usb_log_button = usb_button

            def start_info() -> None:
                if getattr(self, "busy", False):
                    return
                device = self._selected_device()
                if device is None:
                    messagebox.showwarning("Node-Info", "Bitte zuerst ein USB-Gerät auswählen.", parent=self)
                    return
                self._set_busy(True)

                def worker() -> None:
                    try:
                        self._set_progress(0.12, "Node-Info · Gerät auslesen")
                        result = services.meshtastic(device.port, "--info", timeout=60, check=False)
                        text = "\n".join(filter(None, (result.stdout, result.stderr)))
                        summary = summary_from_info_text(text)
                        board_key = services.detect_board_from_text(text) or getattr(device, "board_key", None)
                        board_label = services.BOARD_PROFILES.get(board_key or "", {}).get("label", "Unbekannt")
                        firmware = ""
                        for pattern in (
                            r'"firmwareVersion"\s*:\s*"([^"]+)"',
                            r'(?im)^Firmware(?: Version)?\s*[:=]\s*(.+?)\s*$',
                        ):
                            match = re.search(pattern, text)
                            if match:
                                firmware = match.group(1).strip()
                                break
                        build = ""
                        match = re.search(r"(?i)\bBuild\s*[#:= ]\s*(\d+)\b", text)
                        if match:
                            build = match.group(1)
                        self._append_log(
                            f"NODE-INFO · Port={device.port} · Board={board_label} · Firmware={firmware or 'unbekannt'} "
                            f"· Build={build or '–'} · Long={summary.long_name or '–'} · Short={summary.short_name or '–'} "
                            f"· Rolle={summary.role or '–'}"
                        )
                        self._set_progress(1.0, "Node-Info · Fertig")
                        details = (
                            f"Port: {device.port}\n"
                            f"Board: {board_label}\n"
                            f"Firmware: {firmware or 'unbekannt'}"
                            + (f" · Build {build}" if build else "")
                            + f"\nLong Name: {summary.long_name or '–'}\n"
                            f"Short Name: {summary.short_name or '–'}\n"
                            f"Rolle: {summary.role or '–'}"
                        )
                        self.after(0, messagebox.showinfo, "Node-Info", details)
                    except Exception as exc:
                        self._append_log(f"NODE-INFO FEHLER · {type(exc).__name__}: {exc}")
                        self.after(0, messagebox.showerror, "Node-Info fehlgeschlagen", str(exc))
                    finally:
                        self._set_busy(False)

                threading.Thread(target=worker, name="jarnsen-node-info", daemon=True).start()

            info_button = ctk.CTkButton(
                service_bar,
                text="INFO LESEN",
                width=110,
                height=30,
                fg_color=("gray72", "gray28"),
                hover_color=("gray65", "gray35"),
                command=start_info,
            )
            info_button.pack(side="left", padx=(0, 8))
            service_buttons.append(info_button)

            def start_reboot() -> None:
                if getattr(self, "busy", False):
                    return
                device = self._selected_device()
                if device is None:
                    messagebox.showwarning("Node neu starten", "Bitte zuerst ein USB-Gerät auswählen.", parent=self)
                    return
                self._set_busy(True)

                def worker() -> None:
                    try:
                        self._set_progress(0.20, "Node neu starten · Reboot senden")
                        self._append_log(f"NODE-REBOOT START · Port={device.port}")
                        services.reboot_node(device.port)
                        self._set_progress(0.55, "Node neu starten · Auf USB warten")
                        services.wait_for_serial(device.port, timeout=90)
                        self._set_progress(1.0, "Node neu starten · Fertig")
                        self._append_log(f"NODE-REBOOT ENDE · Port={device.port} · ERFOLG")
                    except Exception as exc:
                        self._append_log(f"NODE-REBOOT FEHLER · {type(exc).__name__}: {exc}")
                        self.after(0, messagebox.showerror, "Neustart fehlgeschlagen", str(exc))
                    finally:
                        self._set_busy(False)

                threading.Thread(target=worker, name="jarnsen-node-reboot", daemon=True).start()

            reboot_button = ctk.CTkButton(
                service_bar,
                text="NEUSTART",
                width=105,
                height=30,
                fg_color=("gray72", "gray28"),
                hover_color=("gray65", "gray35"),
                command=start_reboot,
            )
            reboot_button.pack(side="left")
            service_buttons.append(reboot_button)

            # --- Single-device / series mode switch --------------------------------
            action_children = list(action_card.winfo_children())
            if len(action_children) >= 9:
                title_widget = action_children[0]
                single_desc = action_children[1]
                progress_widget = action_children[2]
                flash_button = action_children[3]
                separator = action_children[4]
                series_title = action_children[5]
                series_desc = action_children[6]
                series_status = action_children[7]
                series_buttons_frame = action_children[8]
                series_widgets = [separator, series_title, series_desc, series_status, series_buttons_frame]

                mode_var = ctk.StringVar(value="Einzelgerät")
                mode_switch = ctk.CTkSegmentedButton(
                    action_card,
                    values=["Einzelgerät", "Serie"],
                    variable=mode_var,
                    height=30,
                )
                try:
                    mode_switch.pack(fill="x", padx=18, pady=(0, 10), after=title_widget)
                except Exception:
                    mode_switch.pack(fill="x", padx=18, pady=(0, 10))

                def show_single() -> None:
                    for widget in series_widgets:
                        try:
                            widget.pack_forget()
                        except Exception:
                            pass
                    try:
                        single_desc.pack(fill="x", padx=18, pady=(0, 10), after=mode_switch)
                        progress_widget.pack(fill="x", padx=18, pady=(0, 12), after=single_desc)
                        flash_button.pack(fill="x", padx=18, pady=(0, 12), after=progress_widget)
                    except Exception:
                        pass

                def show_series() -> None:
                    try:
                        single_desc.pack_forget()
                        flash_button.pack_forget()
                    except Exception:
                        pass
                    try:
                        progress_widget.pack(fill="x", padx=18, pady=(0, 12), after=mode_switch)
                        separator.pack(fill="x", padx=18, pady=(0, 10), after=progress_widget)
                        series_title.pack(anchor="w", padx=18, pady=(0, 4), after=separator)
                        series_desc.pack(fill="x", padx=18, pady=(0, 8), after=series_title)
                        series_status.pack(fill="x", padx=18, pady=(0, 8), after=series_desc)
                        series_buttons_frame.pack(fill="x", padx=18, pady=(0, 12), after=series_status)
                    except Exception:
                        pass

                def mode_changed(value: str) -> None:
                    if value == "Serie":
                        show_series()
                    else:
                        show_single()
                    _emit(f"UI ACTION MODE mode={value}")

                mode_switch.configure(command=mode_changed)
                show_single()
                self.operation_mode = mode_var

            # --- Protocol toolbar and compact/large mode ----------------------------
            log_title = next((w for w in log_card.winfo_children() if _text(w) == "PROTOKOLL"), None)
            toolbar = ctk.CTkFrame(log_card, fg_color="transparent")
            if log_title is not None:
                try:
                    toolbar.pack(fill="x", padx=18, pady=(0, 7), after=log_title, before=self.log_box)
                except Exception:
                    toolbar.pack(fill="x", padx=18, pady=(0, 7))
            else:
                toolbar.pack(fill="x", padx=18, pady=(0, 7))

            expanded = {"value": False}
            toggle_button: Any

            def apply_log_size() -> None:
                if expanded["value"]:
                    try:
                        self.body.grid_rowconfigure(3, weight=6, minsize=300)
                        self.log_box.configure(height=300)
                        toggle_button.configure(text="PROTOKOLL KOMPAKT")
                    except Exception:
                        pass
                else:
                    try:
                        self.body.grid_rowconfigure(3, weight=3, minsize=185)
                        self.log_box.configure(height=165)
                        toggle_button.configure(text="PROTOKOLL GROSS")
                    except Exception:
                        pass

            def toggle_log() -> None:
                expanded["value"] = not expanded["value"]
                apply_log_size()

            toggle_button = ctk.CTkButton(
                toolbar,
                text="PROTOKOLL GROSS",
                width=135,
                height=28,
                fg_color=("gray72", "gray28"),
                hover_color=("gray65", "gray35"),
                command=toggle_log,
            )
            toggle_button.pack(side="left", padx=(0, 7))

            def copy_log() -> None:
                try:
                    text = self.log_box.get("1.0", "end-1c")
                    self.clipboard_clear()
                    self.clipboard_append(text)
                    self._append_log("PROTOKOLL · sichtbaren Inhalt in Zwischenablage kopiert")
                except Exception as exc:
                    messagebox.showerror("Protokoll kopieren", str(exc), parent=self)

            ctk.CTkButton(
                toolbar,
                text="KOPIEREN",
                width=95,
                height=28,
                fg_color=("gray72", "gray28"),
                hover_color=("gray65", "gray35"),
                command=copy_log,
            ).pack(side="left", padx=(0, 7))
            ctk.CTkButton(
                toolbar,
                text="LOGORDNER",
                width=105,
                height=28,
                fg_color=("gray72", "gray28"),
                hover_color=("gray65", "gray35"),
                command=lambda: _open_folder(Path(self.log_path).parent),
            ).pack(side="left")
            apply_log_size()

            # Keep the header calm. Full detail still goes through the original
            # _set_progress into the verbose protocol; only the header is shortened.
            original_set_progress = self._set_progress

            def compact_progress(value: float, text: str) -> None:
                original_set_progress(value, text)
                pct = max(0, min(100, int(round(float(value) * 100))))
                stage = str(text or "").split(" · ", 1)[0].strip() or "Fortschritt"
                count = re.search(r"\b(\d+)/(\d+)\b", str(text or ""))
                compact = f"{pct}% · {stage}"
                if count:
                    compact += f" · {count.group(1)}/{count.group(2)}"
                try:
                    self.after(0, self.status_var.set, compact)
                except Exception:
                    pass

            self._set_progress = compact_progress

            original_set_busy = self._set_busy

            def wrapped_set_busy(busy: bool) -> None:
                original_set_busy(busy)
                state = "disabled" if busy else "normal"
                for button in service_buttons:
                    try:
                        self.after(0, button.configure, {"state": state})
                    except Exception:
                        pass

            self._set_busy = wrapped_set_busy
            _emit(
                "DASHBOARD CLEANUP installed columns=9:10 action-tabs=1 service-bar=1 "
                "protocol-toggle=1 compact-status=1"
            )

        try:
            self.after(1350, patch_app)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init
    _emit("DASHBOARD CLEANUP layer installed")
