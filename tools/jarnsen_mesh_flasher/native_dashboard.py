from __future__ import annotations

import os
import subprocess
import threading
import types
from pathlib import Path
from tkinter import messagebox
from typing import Any

import customtkinter as ctk

from _build_version import APP_VERSION
from native_actions import (
    check_github_firmware,
    choose_local_firmware,
    choose_profile,
    edit_current_profile,
    read_node_info,
    restart_node,
    start_firmware_only,
    start_profile_only,
    start_usb_log,
)


BG = "#07111E"
CARD = "#0B1725"
BORDER = "#23364A"
CONTROL = "#15263A"
CONTROL_HOVER = "#1D344C"
INPUT = "#091624"
BLUE = "#0B72E7"
BLUE_HOVER = "#0862C6"
ORANGE = "#D97706"
ORANGE_HOVER = "#B45309"
GREEN = "#15803D"
GREEN_DARK = "#0F5132"
MUTED = "#94A6BA"
TEXT = "#E8EEF5"


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _button(parent: Any, text: str, command, *, primary: bool = False, orange: bool = False) -> ctk.CTkButton:
    if orange:
        fg, hover, border = ORANGE, ORANGE_HOVER, "#F59E0B"
    elif primary:
        fg, hover, border = BLUE, BLUE_HOVER, "#1683F5"
    else:
        fg, hover, border = CONTROL, CONTROL_HOVER, "#2A4057"
    return ctk.CTkButton(
        parent,
        text=text,
        command=command,
        height=36,
        corner_radius=7,
        border_width=1,
        border_color=border,
        fg_color=fg,
        hover_color=hover,
        font=ctk.CTkFont(size=10, weight="bold"),
    )


def _card(parent: Any, title: str) -> ctk.CTkFrame:
    frame = ctk.CTkFrame(
        parent,
        corner_radius=10,
        fg_color=CARD,
        border_width=1,
        border_color=BORDER,
    )
    ctk.CTkLabel(
        frame,
        text=title,
        font=ctk.CTkFont(size=11, weight="bold"),
        text_color=TEXT,
        anchor="w",
    ).pack(fill="x", padx=14, pady=(9, 5))
    return frame


def install(services: Any) -> None:
    """Replace the legacy patched dashboard once, before the first visible refresh."""
    if getattr(services, "_jarnsen_native_dashboard_layer", False):
        return
    services._jarnsen_native_dashboard_layer = True

    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def build_when_ready(attempt: int = 0) -> None:
            if getattr(self, "_jarnsen_native_dashboard_ready", False):
                return
            required = (
                "device_var",
                "board_var",
                "firmware_var",
                "profile_summary_var",
                "profile_path_var",
                "long_name_var",
                "short_name_var",
                "status_var",
                "_selected_device",
                "_selected_board_key",
                "_set_busy",
                "_set_progress",
                "_append_log",
                "refresh_devices",
                "read_master_profile",
                "check_firmware",
                "start_flash",
                "start_series",
                "stop_series",
            )
            if not all(hasattr(self, name) for name in required):
                if attempt < 20:
                    self.after_idle(lambda: build_when_ready(attempt + 1))
                return
            _build_dashboard(self, services)

        self.after_idle(build_when_ready)

    ctk.CTk.__init__ = root_init
    _emit("NATIVE DASHBOARD bootstrap installed")


def _build_dashboard(app: Any, services: Any) -> None:
    app._jarnsen_native_dashboard_ready = True

    # Stop all legacy delayed UI injectors. Their underlying service functions stay available.
    for flag in (
        "_jarnsen_local_firmware_ui",
        "_jarnsen_profile_only_installed",
        "_jarnsen_profile_editor_installed",
        "_jarnsen_firmware_only_installed",
        "_jarnsen_usb_log_installed",
        "_jarnsen_firmware_status_installed",
        "_jarnsen_dashboard_cleanup_installed",
        "_jarnsen_action_polish_installed",
        "_jarnsen_overlap_guard_installed",
        "_jarnsen_final_layout_installed",
        "_jarnsen_target_layout_installed",
        "_jarnsen_1080_fit_installed",
        "_jarnsen_reference_exact_installed",
    ):
        setattr(app, flag, True)

    try:
        app.configure(fg_color=BG)
        app.state("zoomed")
    except Exception:
        pass

    # The old UI is only a construction scaffold. Remove it before the window is painted.
    for child in list(app.winfo_children()):
        try:
            child.destroy()
        except Exception:
            pass

    app.grid_columnconfigure(0, weight=1)
    app.grid_rowconfigure(1, weight=1)

    # ------------------------------------------------------------------ header
    header = ctk.CTkFrame(app, fg_color="transparent", height=52)
    header.grid(row=0, column=0, sticky="ew", padx=24, pady=(7, 5))
    header.grid_columnconfigure(4, weight=1)

    ctk.CTkLabel(
        header,
        text="J",
        width=38,
        height=38,
        corner_radius=8,
        fg_color=BLUE,
        text_color="white",
        font=ctk.CTkFont(size=22, weight="bold"),
    ).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 12))
    ctk.CTkLabel(
        header,
        text="JARNSEN MESH Flasher",
        font=ctk.CTkFont(size=25, weight="bold"),
    ).grid(row=0, column=1, rowspan=2, sticky="w")
    ctk.CTkLabel(
        header,
        text=APP_VERSION,
        font=ctk.CTkFont(size=10),
        text_color=MUTED,
    ).grid(row=0, column=2, rowspan=2, sticky="w", padx=(12, 0), pady=(8, 0))

    app.native_device_count_var = ctk.StringVar(value="0 Gerät(e) gefunden")
    app.native_board_count_var = ctk.StringVar(value="0 Board(s) erkannt")
    app.native_ready_var = ctk.StringVar(value="Bereit")

    right = ctk.CTkFrame(header, fg_color="transparent")
    right.grid(row=0, column=5, rowspan=2, sticky="e")
    ctk.CTkLabel(right, text="⚯", font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 5))
    ctk.CTkLabel(right, textvariable=app.native_device_count_var, font=ctk.CTkFont(size=10, weight="bold")).pack(side="left", padx=(0, 28))
    ctk.CTkLabel(right, text="▣", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 5))
    ctk.CTkLabel(right, textvariable=app.native_board_count_var, font=ctk.CTkFont(size=10, weight="bold")).pack(side="left", padx=(0, 28))
    ctk.CTkLabel(right, text="●", text_color="#22C55E", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left", padx=(0, 6))
    app.status_label = ctk.CTkLabel(right, textvariable=app.native_ready_var, font=ctk.CTkFont(size=10, weight="bold"))
    app.status_label.pack(side="left")

    # ------------------------------------------------------------------ body grid
    body = ctk.CTkFrame(app, fg_color="transparent")
    body.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 4))
    body.grid_columnconfigure(0, weight=1, uniform="native-columns")
    body.grid_columnconfigure(1, weight=1, uniform="native-columns")
    body.grid_rowconfigure(0, weight=0, minsize=150)
    body.grid_rowconfigure(1, weight=0, minsize=145)
    body.grid_rowconfigure(2, weight=0, minsize=96)
    body.grid_rowconfigure(3, weight=0, minsize=160)
    body.grid_rowconfigure(4, weight=1, minsize=170)
    app.body = body

    device = _card(body, "▣  1. GERÄT")
    profile = _card(body, "⚙  2. GRUNDEINSTELLUNGEN")
    identity = _card(body, "●  3. IDENTITÄT")
    service = _card(body, "⌕  SERVICE")
    firmware = _card(body, "▦  4. FIRMWARE")
    automatic = _card(body, "◷  5. AUTOMATISCHER ABLAUF")
    hints = _card(body, "◉  Hinweise")
    protocol = _card(body, "☷  PROTOKOLL")

    device.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 7))
    profile.grid(row=1, column=0, sticky="nsew", padx=(0, 4), pady=(0, 7))
    identity.grid(row=1, column=1, sticky="nsew", padx=(4, 0), pady=(0, 7))
    service.grid(row=2, column=0, sticky="nsew", padx=(0, 4), pady=(0, 7))
    firmware.grid(row=2, column=1, sticky="nsew", padx=(4, 0), pady=(0, 7))
    automatic.grid(row=3, column=0, sticky="nsew", padx=(0, 4), pady=(0, 7))
    hints.grid(row=3, column=1, sticky="nsew", padx=(4, 0), pady=(0, 7))
    protocol.grid(row=4, column=0, columnspan=2, sticky="nsew")

    # ------------------------------------------------------------------ device
    top = ctk.CTkFrame(device, fg_color="transparent")
    top.pack(fill="x", padx=14, pady=(0, 6))
    top.grid_columnconfigure(0, weight=5)
    top.grid_columnconfigure(1, weight=0)
    top.grid_columnconfigure(2, weight=4)

    com_wrap = ctk.CTkFrame(top, fg_color="transparent")
    com_wrap.grid(row=0, column=0, sticky="ew", padx=(0, 10))
    ctk.CTkLabel(com_wrap, text="COM / Gerät", font=ctk.CTkFont(size=9), text_color=MUTED).pack(anchor="w", pady=(0, 2))
    app.device_combo = ctk.CTkComboBox(
        com_wrap,
        variable=app.device_var,
        values=["Kein Gerät erkannt"],
        command=app._device_changed,
        state="readonly",
        height=32,
        corner_radius=6,
        fg_color=INPUT,
        border_color="#344A5F",
        button_color=CONTROL,
        button_hover_color=CONTROL_HOVER,
    )
    app.device_combo.pack(fill="x")

    search_button = _button(top, "⌕  Neu suchen", app.refresh_devices, primary=True)
    search_button.configure(width=132, height=32)
    search_button.grid(row=0, column=1, sticky="s", padx=(0, 12))

    board_wrap = ctk.CTkFrame(top, fg_color="transparent")
    board_wrap.grid(row=0, column=2, sticky="ew")
    ctk.CTkLabel(board_wrap, text="Board", font=ctk.CTkFont(size=9), text_color=MUTED).pack(anchor="w", pady=(0, 2))
    board_menu = ctk.CTkOptionMenu(
        board_wrap,
        variable=app.board_var,
        values=[
            "Automatisch",
            services.BOARD_PROFILES["tracker"]["label"],
            services.BOARD_PROFILES["repeater"]["label"],
        ],
        command=lambda _value: app._invalidate_bundle(),
        height=32,
        corner_radius=6,
        fg_color=CONTROL,
        button_color=CONTROL_HOVER,
        button_hover_color="#29445E",
    )
    board_menu.pack(fill="x")

    app.installed_firmware_var = ctk.StringVar(value="Installiert: wird gelesen")
    app.available_firmware_var = ctk.StringVar(value="Verfügbar: noch nicht geprüft")
    app.firmware_compare_var = ctk.StringVar(value="")

    status = ctk.CTkFrame(device, fg_color="#0A1623", corner_radius=7, border_width=1, border_color="#475569")
    status.pack(fill="x", padx=14, pady=(0, 8))
    status.grid_columnconfigure(1, weight=1)
    status.grid_columnconfigure(4, weight=1)
    ctk.CTkLabel(status, text="Installierte Firmware:", font=ctk.CTkFont(size=10), text_color=MUTED).grid(row=0, column=0, padx=(12, 7), pady=7, sticky="w")
    installed_value = ctk.StringVar(value="wird gelesen")
    available_value = ctk.StringVar(value="noch nicht geprüft")
    ctk.CTkLabel(status, textvariable=installed_value, font=ctk.CTkFont(size=10, weight="bold"), anchor="w").grid(row=0, column=1, sticky="ew", pady=7)
    ctk.CTkLabel(status, text="|", text_color="#64748B").grid(row=0, column=2, padx=10, pady=7)
    ctk.CTkLabel(status, text="Verfügbare Firmware:", font=ctk.CTkFont(size=10), text_color=MUTED).grid(row=0, column=3, padx=(0, 7), pady=7, sticky="e")
    ctk.CTkLabel(status, textvariable=available_value, font=ctk.CTkFont(size=10, weight="bold"), anchor="w").grid(row=0, column=4, sticky="ew", pady=7)
    firmware_badge = ctk.CTkLabel(status, text="WIRD GEPRÜFT", width=132, height=28, corner_radius=7, fg_color="#374151", font=ctk.CTkFont(size=10, weight="bold"))
    firmware_badge.grid(row=0, column=5, padx=(10, 8), pady=5)

    def show_firmware_details() -> None:
        messagebox.showinfo(
            "Firmwaredetails",
            f"{app.installed_firmware_var.get()}\n\n{app.available_firmware_var.get()}\n\n"
            f"Status: {app.firmware_compare_var.get() or 'noch nicht geprüft'}",
            parent=app,
        )

    details = _button(status, "Details  ▾", show_firmware_details)
    details.configure(width=92, height=28)
    details.grid(row=0, column=6, padx=(0, 8), pady=5)

    # ------------------------------------------------------------------ profile
    profile_line_var = ctk.StringVar(value="")

    def refresh_profile_line(*_args: Any) -> None:
        summary = str(app.profile_summary_var.get() or "").strip()
        raw = str(app.profile_path_var.get() or "").strip()
        filename = Path(raw).name if raw and raw != "Kein Profil geladen" else "–"
        if summary:
            profile_line_var.set(f"{summary}   ·   Profil: {filename}")
        else:
            profile_line_var.set(f"Profil: {filename}")

    ctk.CTkLabel(profile, textvariable=profile_line_var, anchor="w", font=ctk.CTkFont(size=10, weight="bold")).pack(fill="x", padx=14, pady=(0, 8))
    profile_actions = ctk.CTkFrame(profile, fg_color="transparent")
    profile_actions.pack(fill="x", padx=14, pady=(0, 10))
    for col in range(4):
        profile_actions.grid_columnconfigure(col, weight=1, uniform="profile-native")
    profile_specs = (
        ("⇩  MASTER\nEINLESEN", app.read_master_profile, False),
        ("▣  PROFIL\nAUSWÄHLEN", lambda: choose_profile(app, services), True),
        ("⇧  NUR PROFIL\nSCHREIBEN", lambda: start_profile_only(app, services), False),
        ("✎  PROFIL\nBEARBEITEN", lambda: edit_current_profile(app, services), False),
    )
    native_busy_buttons: list[Any] = []
    for idx, (text, command, primary) in enumerate(profile_specs):
        btn = _button(profile_actions, text, command, primary=primary)
        btn.configure(height=48)
        btn.grid(row=0, column=idx, sticky="ew", padx=(0, 4) if idx == 0 else ((4, 4) if idx < 3 else (4, 0)))
        native_busy_buttons.append(btn)
    app.profile_summary_var.trace_add("write", refresh_profile_line)
    app.profile_path_var.trace_add("write", refresh_profile_line)
    refresh_profile_line()

    # ------------------------------------------------------------------ identity
    name_labels = ctk.CTkFrame(identity, fg_color="transparent")
    name_labels.pack(fill="x", padx=14, pady=(0, 2))
    name_labels.grid_columnconfigure(0, weight=4)
    name_labels.grid_columnconfigure(1, weight=1)
    ctk.CTkLabel(name_labels, text="Long Name", font=ctk.CTkFont(size=9), text_color=MUTED).grid(row=0, column=0, sticky="w")
    ctk.CTkLabel(name_labels, text="Short Name", font=ctk.CTkFont(size=9), text_color=MUTED).grid(row=0, column=1, sticky="w", padx=(10, 0))
    names = ctk.CTkFrame(identity, fg_color="transparent")
    names.pack(fill="x", padx=14, pady=(0, 7))
    names.grid_columnconfigure(0, weight=4)
    names.grid_columnconfigure(1, weight=1)
    ctk.CTkEntry(names, textvariable=app.long_name_var, height=32, corner_radius=6, fg_color=INPUT, border_color="#344A5F").grid(row=0, column=0, sticky="ew", padx=(0, 10))
    ctk.CTkEntry(names, textvariable=app.short_name_var, height=32, corner_radius=6, fg_color=INPUT, border_color="#344A5F").grid(row=0, column=1, sticky="ew")
    identity_bar = ctk.CTkFrame(identity, corner_radius=7, fg_color="#143B2C", border_width=1, border_color="#1F6A48")
    identity_bar.pack(fill="x", padx=14, pady=(0, 8))
    ctk.CTkLabel(identity_bar, text="✓  Node aktuell   |   Wird beim nächsten Flash übernommen", anchor="w", font=ctk.CTkFont(size=10, weight="bold"), text_color="#86EFAC").pack(side="left", fill="x", expand=True, padx=10, pady=5)
    ctk.CTkLabel(identity_bar, text="ⓘ", text_color="#86EFAC", font=ctk.CTkFont(size=11, weight="bold")).pack(side="right", padx=(5, 9))

    # ------------------------------------------------------------------ service
    service_row = ctk.CTkFrame(service, fg_color="transparent")
    service_row.pack(fill="x", padx=14, pady=(1, 10))
    for col in range(3):
        service_row.grid_columnconfigure(col, weight=1, uniform="service-native")
    service_specs = (
        ("▧  NODE-LOG USB", lambda: start_usb_log(app, services), True),
        ("ⓘ  INFO LESEN", lambda: read_node_info(app, services), False),
        ("⟳  NEUSTART", lambda: restart_node(app, services), False),
    )
    for idx, (text, command, primary) in enumerate(service_specs):
        btn = _button(service_row, text, command, primary=primary)
        btn.grid(row=0, column=idx, sticky="ew", padx=(0, 4) if idx == 0 else ((4, 4) if idx == 1 else (4, 0)))
        native_busy_buttons.append(btn)
        if idx == 0:
            app.usb_log_button = btn

    # ------------------------------------------------------------------ firmware
    fw_controls = ctk.CTkFrame(firmware, fg_color="transparent")
    fw_controls.pack(fill="x", padx=14, pady=(0, 4))
    fw_controls.grid_columnconfigure(0, weight=0)
    for col in (1, 2, 3):
        fw_controls.grid_columnconfigure(col, weight=1, uniform="firmware-native")
    baud_wrap = ctk.CTkFrame(fw_controls, fg_color="transparent")
    baud_wrap.grid(row=0, column=0, sticky="w", padx=(0, 8))
    ctk.CTkLabel(baud_wrap, text="Baud", font=ctk.CTkFont(size=9), text_color=MUTED).pack(anchor="w", pady=(0, 2))
    baud_value = str(getattr(services, "_jarnsen_flash_baud", "921600"))
    app.native_baud_var = ctk.StringVar(value=baud_value if baud_value in {"115200", "230400", "460800", "921600"} else "921600")
    ctk.CTkOptionMenu(
        baud_wrap,
        variable=app.native_baud_var,
        values=["115200", "230400", "460800", "921600"],
        command=lambda value: setattr(services, "_jarnsen_flash_baud", str(value)),
        width=120,
        height=32,
        corner_radius=6,
        fg_color=CONTROL,
        button_color=CONTROL_HOVER,
    ).pack()
    fw_specs = (
        ("☁  NEUESTE PRÜFEN", lambda: check_github_firmware(app, services), False),
        ("⇧  NUR FIRMWARE UPDATEN", lambda: start_firmware_only(app, services), True),
        ("▧  DATEI VOM PC", lambda: choose_local_firmware(app, services), False),
    )
    for idx, (text, command, orange) in enumerate(fw_specs, start=1):
        btn = _button(fw_controls, text, command, orange=orange)
        btn.grid(row=0, column=idx, sticky="sew", padx=(0, 4) if idx == 1 else ((4, 4) if idx == 2 else (4, 0)), pady=(13, 0))
        native_busy_buttons.append(btn)

    fw_footer = ctk.CTkFrame(firmware, fg_color="transparent")
    fw_footer.pack(fill="x", padx=14, pady=(0, 6))
    fw_footer.grid_columnconfigure(0, weight=1)
    app.native_firmware_summary_var = ctk.StringVar(value="Aktuell: wird gelesen   |   Neueste: noch nicht geprüft")
    ctk.CTkLabel(fw_footer, textvariable=app.native_firmware_summary_var, anchor="w", font=ctk.CTkFont(size=9)).grid(row=0, column=0, sticky="ew")
    fw_small_badge = ctk.CTkLabel(fw_footer, text="Wird geprüft", width=116, height=24, corner_radius=6, fg_color="#374151", font=ctk.CTkFont(size=9, weight="bold"))
    fw_small_badge.grid(row=0, column=1, padx=(8, 0))

    # ------------------------------------------------------------------ automatic
    app.operation_mode = ctk.StringVar(value="Einzelgerät")
    mode_switch = ctk.CTkSegmentedButton(
        automatic,
        values=["Einzelgerät", "Serie"],
        variable=app.operation_mode,
        height=30,
        corner_radius=6,
        selected_color=BLUE,
        selected_hover_color=BLUE_HOVER,
        unselected_color=CONTROL,
        unselected_hover_color=CONTROL_HOVER,
    )
    mode_switch.pack(fill="x", padx=14, pady=(0, 7))

    timeline = ctk.CTkFrame(automatic, fg_color="transparent")
    timeline.pack(fill="x", padx=14, pady=(0, 6))
    stage_names = ("Backup", "Firmware", "Grundeinst.", "Namen", "Neustart", "Prüfung")
    stage_labels: list[Any] = []
    for col in range(6):
        timeline.grid_columnconfigure(col, weight=1, uniform="native-stages")
    for idx, name in enumerate(stage_names):
        lbl = ctk.CTkLabel(timeline, text=("●  " if idx == 0 else "○  ") + name, font=ctk.CTkFont(size=9), text_color="#3B9CFF" if idx == 0 else "#7A8A9A", anchor="w")
        lbl.grid(row=0, column=idx, sticky="w")
        stage_labels.append(lbl)

    progress_row = ctk.CTkFrame(automatic, fg_color="transparent")
    progress_row.pack(fill="x", padx=14, pady=(0, 7))
    app.progress = ctk.CTkProgressBar(progress_row, height=7, corner_radius=4, progress_color=BLUE, fg_color="#294055")
    app.progress.pack(side="left", fill="x", expand=True)
    app.progress.set(0)
    progress_pct = ctk.StringVar(value="0%")
    ctk.CTkLabel(progress_row, textvariable=progress_pct, width=34, anchor="e", font=ctk.CTkFont(size=9)).pack(side="left", padx=(8, 0))

    def run_primary() -> None:
        if str(app.operation_mode.get()) == "Serie":
            app.start_series()
        else:
            app.start_flash()

    primary = _button(automatic, "▶  AUTOMATISCH FLASHEN", run_primary, primary=True)
    primary.configure(height=38, font=ctk.CTkFont(size=11, weight="bold"))
    primary.pack(fill="x", padx=14, pady=(0, 9))
    app.flash_button = primary
    app.series_button = primary
    app.series_stop_button = ctk.CTkButton(automatic, text="Serie beenden", command=app.stop_series, state="disabled")
    app.series_stop_button.place_forget()

    def mode_changed(value: str) -> None:
        if value == "Einzelgerät":
            if getattr(app, "series_active", False) and not getattr(app, "busy", False):
                try:
                    app.stop_series()
                except Exception:
                    pass
            primary.configure(text="▶  AUTOMATISCH FLASHEN")
        else:
            primary.configure(text="▶  SERIENMODUS STARTEN")

    mode_switch.configure(command=mode_changed)

    # ------------------------------------------------------------------ hints
    hint_text = (
        "• Vor dem Flashen wird automatisch ein Backup der aktuellen Konfiguration erstellt.\n"
        "• Alte Profilversionen werden beim Speichern automatisch archiviert.\n"
        "• Über „Node-Log USB“ kann der Log direkt vom Gerät geladen werden.\n"
        "• Für erste OTA-Installation ggf. serielle Verbindung verwenden.\n"
        "• Weitere Optionen im Profil-Editor (inkl. YAML-Ansicht)."
    )
    ctk.CTkLabel(hints, text=hint_text, anchor="nw", justify="left", font=ctk.CTkFont(size=10), wraplength=700).pack(fill="both", expand=True, padx=14, pady=(0, 9))

    # ------------------------------------------------------------------ protocol
    toolbar = ctk.CTkFrame(protocol, fg_color="transparent")
    toolbar.pack(fill="x", padx=14, pady=(0, 5))

    def copy_protocol() -> None:
        try:
            text = app.log_box.get("1.0", "end-1c")
            app.clipboard_clear()
            app.clipboard_append(text)
            app._set_status("Protokoll kopiert")
        except Exception:
            pass

    def open_log_folder() -> None:
        folder = Path(app.log_path).parent
        try:
            if os.name == "nt":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif os.name == "posix":
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            messagebox.showerror("Logordner", str(exc), parent=app)

    def clear_protocol() -> None:
        try:
            app.log_box.configure(state="normal")
            app.log_box.delete("1.0", "end")
            app.log_box.configure(state="disabled")
        except Exception:
            pass

    expanded = {"value": False}

    def toggle_protocol() -> None:
        expanded["value"] = not expanded["value"]
        if expanded["value"]:
            profile.grid_remove(); identity.grid_remove(); service.grid_remove(); firmware.grid_remove(); automatic.grid_remove(); hints.grid_remove()
            body.grid_rowconfigure(1, minsize=0); body.grid_rowconfigure(2, minsize=0); body.grid_rowconfigure(3, minsize=0)
            toggle.configure(text="PROTOKOLL KOMPAKT")
        else:
            profile.grid(); identity.grid(); service.grid(); firmware.grid(); automatic.grid(); hints.grid()
            body.grid_rowconfigure(1, minsize=145); body.grid_rowconfigure(2, minsize=96); body.grid_rowconfigure(3, minsize=160)
            toggle.configure(text="PROTOKOLL GROSS")

    toggle = _button(toolbar, "PROTOKOLL GROSS", toggle_protocol)
    copy_btn = _button(toolbar, "KOPIEREN", copy_protocol)
    folder_btn = _button(toolbar, "LOGORDNER", open_log_folder)
    clear_btn = _button(toolbar, "PROTOKOLL LEEREN", clear_protocol)
    for btn in (toggle, copy_btn, folder_btn, clear_btn):
        btn.configure(height=28, font=ctk.CTkFont(size=9, weight="bold"))
    toggle.pack(side="left", padx=(0, 7))
    copy_btn.pack(side="left", padx=(0, 7))
    folder_btn.pack(side="left")
    clear_btn.pack(side="right")

    app.log_box = ctk.CTkTextbox(protocol, corner_radius=7, fg_color="#06111D", border_width=0, font=ctk.CTkFont(family="Consolas", size=10))
    app.log_box.pack(fill="both", expand=True, padx=14, pady=(0, 8))
    app.log_box.configure(state="disabled")

    # ------------------------------------------------------------------ footer
    footer = ctk.CTkFrame(app, fg_color="transparent", height=22)
    footer.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 4))
    ctk.CTkLabel(footer, text=f"JARNSEN MESH Flasher   ·   {APP_VERSION}", font=ctk.CTkFont(size=9), text_color=MUTED).pack(side="left")
    ctk.CTkLabel(footer, text="© 2026 JARNSEN   |", font=ctk.CTkFont(size=9), text_color=MUTED).pack(side="right", padx=(0, 8))
    ctk.CTkLabel(footer, textvariable=app.native_ready_var, font=ctk.CTkFont(size=9, weight="bold")).pack(side="right", padx=(0, 8))
    ctk.CTkLabel(footer, text="●", text_color="#22C55E", font=ctk.CTkFont(size=11)).pack(side="right", padx=(0, 5))

    # ------------------------------------------------------------------ state wiring
    def refresh_counts() -> None:
        try:
            devices = list(getattr(app, "devices", []) or [])
            boards = sum(1 for item in devices if getattr(item, "board_key", None))
            app.native_device_count_var.set(f"{len(devices)} Gerät(e) gefunden")
            app.native_board_count_var.set(f"{boards} Board(s) erkannt")
            app.after(1200, refresh_counts)
        except Exception:
            pass

    generation = {"value": 0}

    def refresh_firmware_status(force: bool = False) -> None:
        from firmware_status_ui import (
            _installed_display,
            comparison_text,
            latest_available,
            parse_installed_firmware,
            query_jarnsen_identity,
        )

        generation["value"] += 1
        token = generation["value"]
        device_info = app._selected_device()
        board_key = app._selected_board_key()
        if device_info is None:
            app.installed_firmware_var.set("Installiert: kein Gerät")
            app.available_firmware_var.set("Verfügbar: Board zuerst erkennen")
            app.firmware_compare_var.set("")
            return

        fallback = parse_installed_firmware(getattr(device_info, "model_text", ""))
        app.installed_firmware_var.set(f"Installiert: {_installed_display(fallback)}")
        if board_key not in services.BOARD_PROFILES:
            app.available_firmware_var.set("Verfügbar: Board nicht erkannt")
            app.firmware_compare_var.set("Board auswählen")
            return

        local = getattr(services, "_jarnsen_local_firmware_bundle", None)
        if local is not None and getattr(local, "board_key", None) == board_key:
            app.available_firmware_var.set(f"Verfügbar: {local.display_name} · PC-Datei")
            app.firmware_compare_var.set("PC-DATEI AUSGEWÄHLT")
            return

        app.available_firmware_var.set("Verfügbar: GitHub wird geprüft …")

        def worker() -> None:
            try:
                identity = query_jarnsen_identity(device_info.port) or fallback
                available = latest_available(services, board_key, force=force)
                state, detail = comparison_text(identity, available)

                def update() -> None:
                    if token != generation["value"]:
                        return
                    app.installed_firmware_var.set(f"Installiert: {_installed_display(identity)}")
                    app.available_firmware_var.set(f"Verfügbar: JARNSEN-MESH v{available.version} · Build {available.build}")
                    app.firmware_compare_var.set(f"{state} · {detail}")
                    app._append_log(
                        f"FIRMWARE STATUS · Port={device_info.port} · Installiert={_installed_display(identity)} · "
                        f"Verfügbar=JARNSEN-MESH v{available.version} Build {available.build} · Status={state}"
                    )

                app.after(0, update)
            except Exception as exc:
                def fail() -> None:
                    if token != generation["value"]:
                        return
                    app.available_firmware_var.set("Verfügbar: GitHub-Prüfung fehlgeschlagen")
                    app.firmware_compare_var.set(str(exc))
                app.after(0, fail)

        threading.Thread(target=worker, name="jarnsen-native-fw-status", daemon=True).start()

    app.refresh_firmware_status = refresh_firmware_status

    def refresh_firmware_labels(*_args: Any) -> None:
        installed_raw = str(app.installed_firmware_var.get() or "")
        available_raw = str(app.available_firmware_var.get() or "")
        compare = str(app.firmware_compare_var.get() or "").strip()
        installed_value.set(installed_raw.removeprefix("Installiert:").strip() or "wird gelesen")
        available_value.set(available_raw.removeprefix("Verfügbar:").strip() or "noch nicht geprüft")
        app.native_firmware_summary_var.set(
            f"Aktuell: {installed_value.get()}   |   Neueste: {available_value.get()}"
        )
        upper = compare.upper()
        if upper.startswith("AKTUELL"):
            firmware_badge.configure(text="AKTUELL", fg_color=GREEN)
            fw_small_badge.configure(text="Aktuell", fg_color=GREEN)
            status.configure(border_color="#22C55E")
        elif upper.startswith("UPDATE VERFÜGBAR") or upper.startswith("ANDERE FIRMWARE") or upper.startswith("JARNSEN-MESH VERFÜGBAR"):
            firmware_badge.configure(text="UPDATE EMPFOHLEN", fg_color=ORANGE)
            fw_small_badge.configure(text="⚠  Update verfügbar", fg_color="#9A4D00")
            status.configure(border_color="#F59E0B")
        elif upper.startswith("PC-DATEI"):
            firmware_badge.configure(text="PC-DATEI", fg_color=BLUE)
            fw_small_badge.configure(text="PC-Datei", fg_color=BLUE)
            status.configure(border_color="#3B82F6")
        elif upper.startswith("NEUER ALS GITHUB"):
            firmware_badge.configure(text="NODE NEUER", fg_color="#1E4E79")
            fw_small_badge.configure(text="Node neuer", fg_color="#1E4E79")
            status.configure(border_color="#60A5FA")
        else:
            firmware_badge.configure(text="WIRD GEPRÜFT", fg_color="#374151")
            fw_small_badge.configure(text="Wird geprüft", fg_color="#374151")
            status.configure(border_color="#475569")

    for var in (app.installed_firmware_var, app.available_firmware_var, app.firmware_compare_var):
        var.trace_add("write", refresh_firmware_labels)
    refresh_firmware_labels()

    def queue_fw_refresh(*_args: Any) -> None:
        app.after(220, refresh_firmware_status)

    app.device_var.trace_add("write", queue_fw_refresh)
    app.board_var.trace_add("write", queue_fw_refresh)

    original_set_progress = app._set_progress

    def native_set_progress(value: float, text: str) -> None:
        original_set_progress(value, text)
        fraction = max(0.0, min(1.0, float(value)))
        progress_pct.set(f"{int(round(fraction * 100))}%")
        if fraction < 0.35:
            active = 0
        elif fraction < 0.79:
            active = 1
        elif fraction < 0.88:
            active = 2
        elif fraction < 0.94:
            active = 3
        elif fraction < 0.98:
            active = 4
        else:
            active = 5

        def update_stage() -> None:
            for idx, label in enumerate(stage_labels):
                if idx < active:
                    label.configure(text="●  " + stage_names[idx], text_color="#22C55E")
                elif idx == active:
                    label.configure(text="●  " + stage_names[idx], text_color="#3B9CFF")
                else:
                    label.configure(text="○  " + stage_names[idx], text_color="#7A8A9A")

        app.after(0, update_stage)

    app._set_progress = native_set_progress

    original_set_busy = app._set_busy

    def native_set_busy(busy: bool) -> None:
        original_set_busy(busy)
        state = "disabled" if busy else "normal"
        app.native_ready_var.set("Arbeitet …" if busy else "Bereit")
        for btn in native_busy_buttons:
            try:
                btn.configure(state=state)
            except Exception:
                pass

    app._set_busy = native_set_busy

    refresh_counts()
    refresh_profile_line()
    app.after(420, refresh_firmware_status)
    try:
        app._append_log("UI · Native Referenzoberfläche aktiv · keine verzögerten Layout-Patch-Kaskaden")
    except Exception:
        pass
    _emit("NATIVE DASHBOARD ready architecture=single-build layout=reference-1920x1080")
