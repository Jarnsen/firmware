from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from tkinter import messagebox
from typing import Any

import customtkinter as ctk
from _build_version import APP_VERSION
from functional_profiles import (
    SELECT_PLACEHOLDER,
    activate_functional_profile,
    activate_selected_functional_profile,
    active_profile,
)
from functional_profiles import labels as functional_profile_labels
from functional_profiles import read_master_into_functional_profile
from native_actions import (
    choose_local_firmware,
    edit_current_profile,
    read_node_info,
    restart_node,
    start_firmware_only,
    start_profile_only,
    start_usb_log,
)
from ui_icons import icon

BG = "#06111E"
CARD = "#0A1725"
BORDER = "#23364A"
CONTROL = "#15273A"
CONTROL_HOVER = "#1D354D"
INPUT = "#081522"
BLUE = "#0B72E7"
BLUE_HOVER = "#0862C6"
ORANGE = "#D97706"
ORANGE_HOVER = "#B45309"
GREEN = "#15803D"
MUTED = "#93A6BA"
TEXT = "#EAF0F7"
FONT = "Segoe UI"

# Tuned against the approved 1920x1080 / 125% reference proportions.
ROW_DEVICE = 146
ROW_INFO = 134
ROW_SERVICE = 80
ROW_ACTION = 130
ROW_PROTOCOL_MIN = 145
GAP = 6


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _font(size: int, weight: str = "normal", family: str = FONT) -> ctk.CTkFont:
    return ctk.CTkFont(family=family, size=size, weight=weight)


def _button(
    parent: Any,
    text: str,
    command,
    *,
    icon_name: str | None = None,
    primary: bool = False,
    orange: bool = False,
    height: int = 30,
    font_size: int = 9,
) -> ctk.CTkButton:
    if orange:
        fg, hover, border = ORANGE, ORANGE_HOVER, "#F59E0B"
    elif primary:
        fg, hover, border = BLUE, BLUE_HOVER, "#1683F5"
    else:
        fg, hover, border = CONTROL, CONTROL_HOVER, "#2A4057"
    kwargs: dict[str, Any] = {}
    if icon_name:
        kwargs["image"] = icon(icon_name, 13, "#F8FAFC")
        kwargs["compound"] = "left"
    return ctk.CTkButton(
        parent,
        text=text,
        command=command,
        height=height,
        corner_radius=6,
        border_width=1,
        border_color=border,
        fg_color=fg,
        hover_color=hover,
        font=_font(font_size, "bold"),
        **kwargs,
    )


def _card(parent: Any, title: str, icon_name: str) -> ctk.CTkFrame:
    frame = ctk.CTkFrame(
        parent,
        corner_radius=8,
        fg_color=CARD,
        border_width=1,
        border_color=BORDER,
    )
    title_row = ctk.CTkFrame(frame, fg_color="transparent", height=20)
    title_row.pack(fill="x", padx=12, pady=(6, 3))
    ctk.CTkLabel(
        title_row, text="", image=icon(icon_name, 13, TEXT), width=15, height=15
    ).pack(side="left", padx=(0, 7))
    ctk.CTkLabel(
        title_row,
        text=title,
        font=_font(10, "bold"),
        text_color=TEXT,
        anchor="w",
    ).pack(side="left", fill="x", expand=True)
    return frame


def _dot(parent: Any, color: str = "#22C55E", size: int = 8) -> ctk.CTkLabel:
    return ctk.CTkLabel(
        parent,
        text="",
        width=size,
        height=size,
        corner_radius=size // 2,
        fg_color=color,
    )


def _build_dashboard(app: Any, services: Any) -> None:
    """Build the approved reference dashboard once, directly from FlasherApp._build_ui."""
    if getattr(app, "_jarnsen_native_dashboard_ready", False):
        return
    app._jarnsen_native_dashboard_ready = True
    app._jarnsen_reference_dashboard_v2 = True
    app._jarnsen_design_revision = "reference-v2-pil-icons"

    try:
        app.configure(fg_color=BG)
        app.grid_columnconfigure(0, weight=1)
        app.grid_rowconfigure(0, weight=0)
        app.grid_rowconfigure(1, weight=1)
        app.grid_rowconfigure(2, weight=0)
        app.state("zoomed")
    except Exception:
        pass

    # Defensive only: direct construction normally starts with no content children.
    for child in list(app.winfo_children()):
        try:
            child.destroy()
        except Exception:
            pass

    # --------------------------------------------------------------- header
    header = ctk.CTkFrame(app, fg_color="transparent", height=42)
    header.grid(row=0, column=0, sticky="ew", padx=20, pady=(4, 3))
    header.grid_columnconfigure(3, weight=1)

    ctk.CTkLabel(
        header,
        text="J",
        width=34,
        height=34,
        corner_radius=7,
        fg_color=BLUE,
        text_color="white",
        font=_font(20, "bold"),
    ).grid(row=0, column=0, sticky="w", padx=(0, 10))
    ctk.CTkLabel(
        header,
        text="JARNSEN MESH Flasher",
        font=_font(22, "bold"),
        text_color=TEXT,
    ).grid(row=0, column=1, sticky="w")
    ctk.CTkLabel(
        header,
        text=APP_VERSION,
        font=_font(9),
        text_color=MUTED,
    ).grid(row=0, column=2, sticky="w", padx=(10, 0), pady=(5, 0))

    app.native_device_count_var = ctk.StringVar(value="0 Gerät(e) gefunden")
    app.native_board_count_var = ctk.StringVar(value="0 Board(s) erkannt")
    app.native_ready_var = ctk.StringVar(value="Bereit")

    right = ctk.CTkFrame(header, fg_color="transparent")
    right.grid(row=0, column=4, sticky="e")
    ctk.CTkLabel(right, text="", image=icon("usb", 12, TEXT), width=14).pack(
        side="left", padx=(0, 4)
    )
    ctk.CTkLabel(
        right,
        textvariable=app.native_device_count_var,
        font=_font(9, "bold"),
        text_color=TEXT,
    ).pack(side="left", padx=(0, 23))
    ctk.CTkLabel(right, text="", image=icon("chip", 12, TEXT), width=14).pack(
        side="left", padx=(0, 4)
    )
    ctk.CTkLabel(
        right,
        textvariable=app.native_board_count_var,
        font=_font(9, "bold"),
        text_color=TEXT,
    ).pack(side="left", padx=(0, 23))
    _dot(right, "#22C55E", 8).pack(side="left", padx=(0, 6))
    app.status_label = ctk.CTkLabel(
        right, textvariable=app.native_ready_var, font=_font(9, "bold"), text_color=TEXT
    )
    app.status_label.pack(side="left")

    # --------------------------------------------------------------- body grid
    body = ctk.CTkFrame(app, fg_color="transparent")
    body.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 3))
    body.grid_columnconfigure(0, weight=1, uniform="reference-columns")
    body.grid_columnconfigure(1, weight=1, uniform="reference-columns")
    body.grid_rowconfigure(0, weight=0, minsize=ROW_DEVICE)
    body.grid_rowconfigure(1, weight=0, minsize=ROW_INFO)
    body.grid_rowconfigure(2, weight=0, minsize=ROW_SERVICE)
    body.grid_rowconfigure(3, weight=0, minsize=ROW_ACTION)
    body.grid_rowconfigure(4, weight=1, minsize=ROW_PROTOCOL_MIN)
    app.body = body

    device = _card(body, "1. GERÄT", "device")
    profile = _card(body, "2. GRUNDEINSTELLUNGEN", "settings")
    identity = _card(body, "3. IDENTITÄT", "user")
    service = _card(body, "SERVICE", "wrench")
    firmware = _card(body, "4. FIRMWARE", "chip")
    automatic = _card(body, "5. AUTOMATISCHER ABLAUF", "clock")
    hints = _card(body, "Hinweise", "bulb")

    protocol = ctk.CTkFrame(
        body, corner_radius=8, fg_color=CARD, border_width=1, border_color=BORDER
    )

    device.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, GAP))
    profile.grid(row=1, column=0, sticky="nsew", padx=(0, GAP // 2), pady=(0, GAP))
    identity.grid(row=1, column=1, sticky="nsew", padx=(GAP // 2, 0), pady=(0, GAP))
    service.grid(row=2, column=0, sticky="nsew", padx=(0, GAP // 2), pady=(0, GAP))
    firmware.grid(row=2, column=1, sticky="nsew", padx=(GAP // 2, 0), pady=(0, GAP))
    automatic.grid(row=3, column=0, sticky="nsew", padx=(0, GAP // 2), pady=(0, GAP))
    hints.grid(row=3, column=1, sticky="nsew", padx=(GAP // 2, 0), pady=(0, GAP))
    protocol.grid(row=4, column=0, columnspan=2, sticky="nsew")

    # --------------------------------------------------------------- device
    top = ctk.CTkFrame(device, fg_color="transparent")
    top.pack(fill="x", padx=12, pady=(0, 5))
    top.grid_columnconfigure(0, weight=48)
    top.grid_columnconfigure(1, weight=0)
    top.grid_columnconfigure(2, weight=42)

    com_wrap = ctk.CTkFrame(top, fg_color="transparent")
    com_wrap.grid(row=0, column=0, sticky="ew", padx=(0, 9))
    ctk.CTkLabel(com_wrap, text="COM / Gerät", font=_font(8), text_color=MUTED).pack(
        anchor="w", pady=(0, 1)
    )
    app.device_combo = ctk.CTkComboBox(
        com_wrap,
        variable=app.device_var,
        values=["Kein Gerät erkannt"],
        command=app._device_changed,
        state="readonly",
        height=29,
        corner_radius=5,
        fg_color=INPUT,
        border_color="#344A5F",
        button_color=CONTROL,
        button_hover_color=CONTROL_HOVER,
        font=_font(10),
        dropdown_font=_font(10),
    )
    app.device_combo.pack(fill="x")

    search_button = _button(
        top,
        "Neu suchen",
        app.refresh_devices,
        icon_name="search",
        primary=True,
        height=29,
    )
    search_button.configure(width=122)
    search_button.grid(row=0, column=1, sticky="s", padx=(0, 10))

    board_wrap = ctk.CTkFrame(top, fg_color="transparent")
    board_wrap.grid(row=0, column=2, sticky="ew")
    ctk.CTkLabel(board_wrap, text="Board", font=_font(8), text_color=MUTED).pack(
        anchor="w", pady=(0, 1)
    )
    board_menu = ctk.CTkOptionMenu(
        board_wrap,
        variable=app.board_var,
        values=[
            "Automatisch",
            services.BOARD_PROFILES["tracker"]["label"],
            services.BOARD_PROFILES["repeater"]["label"],
        ],
        command=lambda _value: app._invalidate_bundle(),
        height=29,
        corner_radius=5,
        fg_color=CONTROL,
        button_color=CONTROL_HOVER,
        button_hover_color="#29445E",
        font=_font(10),
        dropdown_font=_font(10),
    )
    board_menu.pack(fill="x")

    app.installed_firmware_var = ctk.StringVar(value="Installiert: wird gelesen")
    app.available_firmware_var = ctk.StringVar(value="Verfügbar: noch nicht geprüft")
    app.firmware_compare_var = ctk.StringVar(value="")
    installed_value = ctk.StringVar(value="wird gelesen")
    available_value = ctk.StringVar(value="noch nicht geprüft")

    status = ctk.CTkFrame(
        device,
        fg_color="#091522",
        corner_radius=6,
        border_width=1,
        border_color="#475569",
        height=28,
    )
    status.pack(fill="x", padx=12, pady=(0, 6))
    status.grid_columnconfigure(2, weight=1)
    status.grid_columnconfigure(5, weight=1)
    ctk.CTkLabel(status, text="", image=icon("chip", 13, MUTED), width=18).grid(
        row=0, column=0, padx=(9, 3), pady=4
    )
    ctk.CTkLabel(
        status, text="Installierte Firmware:", font=_font(8), text_color=MUTED
    ).grid(row=0, column=1, padx=(0, 6), pady=4, sticky="w")
    ctk.CTkLabel(
        status, textvariable=installed_value, font=_font(9, "bold"), anchor="w"
    ).grid(row=0, column=2, sticky="ew", pady=4)
    ctk.CTkLabel(status, text="|", text_color="#64748B", font=_font(9)).grid(
        row=0, column=3, padx=9, pady=4
    )
    ctk.CTkLabel(
        status, text="Verfügbare Firmware:", font=_font(8), text_color=MUTED
    ).grid(row=0, column=4, padx=(0, 6), pady=4, sticky="e")
    ctk.CTkLabel(
        status, textvariable=available_value, font=_font(9, "bold"), anchor="w"
    ).grid(row=0, column=5, sticky="ew", pady=4)
    firmware_badge = ctk.CTkLabel(
        status,
        text="WIRD GEPRÜFT",
        width=122,
        height=24,
        corner_radius=6,
        fg_color="#374151",
        font=_font(9, "bold"),
    )
    firmware_badge.grid(row=0, column=6, padx=(8, 7), pady=3)

    def show_firmware_details() -> None:
        messagebox.showinfo(
            "Firmwaredetails",
            f"{app.installed_firmware_var.get()}\n\n{app.available_firmware_var.get()}\n\nStatus: {app.firmware_compare_var.get() or 'noch nicht geprüft'}",
            parent=app,
        )

    details = _button(status, "Details", show_firmware_details, height=24, font_size=8)
    details.configure(width=82)
    details.grid(row=0, column=7, padx=(0, 7), pady=3)

    # --------------------------------------------------------------- profile
    profile_line_var = ctk.StringVar(value="")

    def refresh_profile_line(*_args: Any) -> None:
        summary = str(app.profile_summary_var.get() or "").strip()
        raw = str(app.profile_path_var.get() or "").strip()
        filename = Path(raw).name if raw and raw != "Kein Profil geladen" else "-"
        profile_line_var.set(
            f"{summary}   ·   Profil: {filename}" if summary else f"Profil: {filename}"
        )

    ctk.CTkLabel(
        profile,
        textvariable=profile_line_var,
        anchor="w",
        font=_font(9, "bold"),
        text_color=TEXT,
    ).pack(fill="x", padx=12, pady=(0, 3))

    selected_function = active_profile(services)
    # A first-flashed device must receive a deliberate function assignment.
    app.functional_profile_var = ctk.StringVar(
        value=selected_function.label if selected_function else SELECT_PLACEHOLDER
    )
    functional_row = ctk.CTkFrame(profile, fg_color="transparent")
    functional_row.pack(fill="x", padx=12, pady=(0, 5))
    ctk.CTkLabel(
        functional_row,
        text="Funktionsprofil",
        width=91,
        anchor="w",
        font=_font(8),
        text_color=MUTED,
    ).pack(side="left")
    app.functional_profile_menu = ctk.CTkOptionMenu(
        functional_row,
        variable=app.functional_profile_var,
        values=functional_profile_labels(),
        command=lambda value: activate_functional_profile(app, services, value),
        height=26,
        corner_radius=5,
        fg_color=CONTROL,
        button_color=CONTROL_HOVER,
        button_hover_color="#29445E",
        font=_font(9, "bold"),
        dropdown_font=_font(9),
    )
    app.functional_profile_menu.pack(side="left", fill="x", expand=True)

    profile_actions = ctk.CTkFrame(profile, fg_color="transparent")
    profile_actions.pack(fill="x", padx=12, pady=(0, 7))
    for col in range(4):
        profile_actions.grid_columnconfigure(col, weight=1, uniform="profile-reference")
    native_busy_buttons: list[Any] = []
    profile_specs = (
        (
            "MASTER\nEINLESEN",
            "download",
            lambda: read_master_into_functional_profile(app, services),
            False,
        ),
        (
            "FUNKTION\nÜBERNEHMEN",
            "folder",
            lambda: activate_selected_functional_profile(app, services),
            True,
        ),
        (
            "NUR PROFIL\nSCHREIBEN",
            "upload",
            lambda: start_profile_only(app, services),
            False,
        ),
        (
            "PROFIL\nBEARBEITEN",
            "edit",
            lambda: edit_current_profile(app, services),
            False,
        ),
    )
    for idx, (text, icon_name, command, primary) in enumerate(profile_specs):
        btn = _button(
            profile_actions,
            text,
            command,
            icon_name=icon_name,
            primary=primary,
            height=40,
            font_size=9,
        )
        btn.grid(
            row=0,
            column=idx,
            sticky="ew",
            padx=(0, 3) if idx == 0 else ((3, 3) if idx < 3 else (3, 0)),
        )
        native_busy_buttons.append(btn)
    app.profile_summary_var.trace_add("write", refresh_profile_line)
    app.profile_path_var.trace_add("write", refresh_profile_line)
    refresh_profile_line()

    # --------------------------------------------------------------- identity
    name_labels = ctk.CTkFrame(identity, fg_color="transparent")
    name_labels.pack(fill="x", padx=12, pady=(0, 1))
    name_labels.grid_columnconfigure(0, weight=4)
    name_labels.grid_columnconfigure(1, weight=1)
    ctk.CTkLabel(name_labels, text="Long Name", font=_font(8), text_color=MUTED).grid(
        row=0, column=0, sticky="w"
    )
    ctk.CTkLabel(name_labels, text="Short Name", font=_font(8), text_color=MUTED).grid(
        row=0, column=1, sticky="w", padx=(9, 0)
    )
    names = ctk.CTkFrame(identity, fg_color="transparent")
    names.pack(fill="x", padx=12, pady=(0, 5))
    names.grid_columnconfigure(0, weight=4)
    names.grid_columnconfigure(1, weight=1)
    ctk.CTkEntry(
        names,
        textvariable=app.long_name_var,
        height=28,
        corner_radius=5,
        fg_color=INPUT,
        border_color="#344A5F",
        font=_font(10),
    ).grid(row=0, column=0, sticky="ew", padx=(0, 9))
    ctk.CTkEntry(
        names,
        textvariable=app.short_name_var,
        height=28,
        corner_radius=5,
        fg_color=INPUT,
        border_color="#344A5F",
        font=_font(10),
    ).grid(row=0, column=1, sticky="ew")
    identity_bar = ctk.CTkFrame(
        identity,
        corner_radius=6,
        fg_color="#143B2C",
        border_width=1,
        border_color="#1F6A48",
        height=25,
    )
    identity_bar.pack(fill="x", padx=12, pady=(0, 6))
    ctk.CTkLabel(
        identity_bar, text="", image=icon("check", 11, "#86EFAC"), width=15
    ).pack(side="left", padx=(8, 4))
    ctk.CTkLabel(
        identity_bar,
        text="Node aktuell   |   Wird beim nächsten Flash übernommen",
        anchor="w",
        font=_font(9, "bold"),
        text_color="#86EFAC",
    ).pack(side="left", fill="x", expand=True, pady=3)
    ctk.CTkLabel(
        identity_bar, text="", image=icon("info", 11, "#86EFAC"), width=15
    ).pack(side="right", padx=(4, 8))

    # --------------------------------------------------------------- service
    service_row = ctk.CTkFrame(service, fg_color="transparent")
    service_row.pack(fill="x", padx=12, pady=(0, 7))
    for col in range(3):
        service_row.grid_columnconfigure(col, weight=1, uniform="service-reference")
    service_specs = (
        ("NODE-LOG USB", "file", lambda: start_usb_log(app, services), True),
        ("INFO LESEN", "info", lambda: read_node_info(app, services), False),
        ("NEUSTART", "refresh", lambda: restart_node(app, services), False),
    )
    for idx, (text, icon_name, command, primary) in enumerate(service_specs):
        btn = _button(
            service_row, text, command, icon_name=icon_name, primary=primary, height=30
        )
        btn.grid(
            row=0,
            column=idx,
            sticky="ew",
            padx=(0, 3) if idx == 0 else ((3, 3) if idx == 1 else (3, 0)),
        )
        native_busy_buttons.append(btn)
        if idx == 0:
            app.usb_log_button = btn

    # --------------------------------------------------------------- firmware
    fw_controls = ctk.CTkFrame(firmware, fg_color="transparent")
    fw_controls.pack(fill="x", padx=12, pady=(0, 2))
    fw_controls.grid_columnconfigure(0, weight=0)
    for col in (1, 2, 3):
        fw_controls.grid_columnconfigure(col, weight=1, uniform="firmware-reference")

    baud_wrap = ctk.CTkFrame(fw_controls, fg_color="transparent")
    baud_wrap.grid(row=0, column=0, sticky="w", padx=(0, 7))
    ctk.CTkLabel(baud_wrap, text="Baud", font=_font(8), text_color=MUTED).pack(
        anchor="w", pady=(0, 1)
    )
    baud_value = str(getattr(services, "_jarnsen_flash_baud", "921600"))
    app.native_baud_var = ctk.StringVar(
        value=(
            baud_value
            if baud_value in {"115200", "230400", "460800", "921600"}
            else "921600"
        )
    )
    ctk.CTkOptionMenu(
        baud_wrap,
        variable=app.native_baud_var,
        values=["115200", "230400", "460800", "921600"],
        command=lambda value: setattr(services, "_jarnsen_flash_baud", str(value)),
        width=104,
        height=27,
        corner_radius=5,
        fg_color=CONTROL,
        button_color=CONTROL_HOVER,
        font=_font(9),
        dropdown_font=_font(9),
    ).pack()
    fw_specs = (
        (
            "VORABCHECK",
            "cloud",
            lambda: __import__("advanced_flasher").start_preflight_check(app, services),
            False,
        ),
        (
            "NUR FIRMWARE UPDATEN",
            "upload",
            lambda: start_firmware_only(app, services),
            True,
        ),
        ("DATEI VOM PC", "file", lambda: choose_local_firmware(app, services), False),
    )
    for idx, (text, icon_name, command, orange) in enumerate(fw_specs, start=1):
        btn = _button(
            fw_controls,
            text,
            command,
            icon_name=icon_name,
            orange=orange,
            height=29,
            font_size=8,
        )
        btn.grid(
            row=0,
            column=idx,
            sticky="sew",
            padx=(0, 3) if idx == 1 else ((3, 3) if idx == 2 else (3, 0)),
            pady=(10, 0),
        )
        native_busy_buttons.append(btn)
        if text == "NUR FIRMWARE UPDATEN":
            app.firmware_only_button = btn

    fw_footer = ctk.CTkFrame(firmware, fg_color="transparent")
    fw_footer.pack(fill="x", padx=12, pady=(0, 4))
    fw_footer.grid_columnconfigure(0, weight=1)
    app.native_firmware_summary_var = ctk.StringVar(
        value="Aktuell: wird gelesen   |   Neueste: noch nicht geprüft"
    )
    ctk.CTkLabel(
        fw_footer,
        textvariable=app.native_firmware_summary_var,
        anchor="w",
        font=_font(8),
        text_color=TEXT,
    ).grid(row=0, column=0, sticky="ew")
    fw_small_badge = ctk.CTkLabel(
        fw_footer,
        text="Wird geprüft",
        width=108,
        height=19,
        corner_radius=5,
        fg_color="#374151",
        font=_font(8, "bold"),
    )
    fw_small_badge.grid(row=0, column=1, padx=(7, 0))

    # --------------------------------------------------------------- automatic
    app.operation_mode = ctk.StringVar(value="Erstflash")
    mode_switch = ctk.CTkSegmentedButton(
        automatic,
        values=["Erstflash", "Reparatur", "Werkseinstellung", "Serie"],
        variable=app.operation_mode,
        height=25,
        corner_radius=5,
        selected_color=BLUE,
        selected_hover_color=BLUE_HOVER,
        unselected_color=CONTROL,
        unselected_hover_color=CONTROL_HOVER,
        font=_font(9),
    )
    mode_switch.pack(fill="x", padx=12, pady=(0, 5))
    app.flash_mode_switch = mode_switch

    timeline = ctk.CTkFrame(automatic, fg_color="transparent", height=20)
    timeline.pack(fill="x", padx=12, pady=(0, 4))
    timeline.pack_propagate(False)
    connector = ctk.CTkFrame(timeline, height=1, fg_color="#36506A")
    connector.place(relx=0.045, rely=0.36, relwidth=0.91)
    stage_names = ("Backup", "Firmware", "Grundeinst.", "Namen", "Neustart", "Prüfung")
    stage_widgets: list[tuple[Any, Any]] = []
    stages = ctk.CTkFrame(timeline, fg_color="transparent")
    stages.place(relx=0, rely=0, relwidth=1, relheight=1)
    for col in range(6):
        stages.grid_columnconfigure(col, weight=1, uniform="timeline-reference")
    for idx, name in enumerate(stage_names):
        holder = ctk.CTkFrame(stages, fg_color="transparent")
        holder.grid(row=0, column=idx, sticky="ew")
        dot_icon = icon(
            "radio_on" if idx == 0 else "radio_off",
            9,
            "#3B9CFF" if idx == 0 else "#6F8498",
        )
        dot_label = ctk.CTkLabel(holder, text="", image=dot_icon, width=10, height=10)
        dot_label.pack(side="left")
        text_label = ctk.CTkLabel(
            holder, text=name, font=_font(7), text_color="#A9B7C5", anchor="w"
        )
        text_label.pack(side="left", padx=(2, 0))
        stage_widgets.append((dot_label, text_label))

    progress_row = ctk.CTkFrame(automatic, fg_color="transparent")
    progress_row.pack(fill="x", padx=12, pady=(0, 4))
    app.progress = ctk.CTkProgressBar(
        progress_row, height=5, corner_radius=3, progress_color=BLUE, fg_color="#294055"
    )
    app.progress.pack(side="left", fill="x", expand=True)
    app.progress.set(0)
    progress_pct = ctk.StringVar(value="0%")
    ctk.CTkLabel(
        progress_row, textvariable=progress_pct, width=78, anchor="e", font=_font(8)
    ).pack(side="left", padx=(6, 0))

    def run_primary() -> None:
        selected_mode = str(app.operation_mode.get())
        if selected_mode == "Serie":
            app.start_series()
        else:
            from advanced_flasher import start_flash_mode

            mode = {
                "Erstflash": "provision",
                "Reparatur": "repair",
                "Werkseinstellung": "factory",
            }.get(selected_mode, "provision")
            start_flash_mode(app, services, mode)

    primary = _button(
        automatic,
        "AUTOMATISCH FLASHEN",
        run_primary,
        icon_name="play",
        primary=True,
        height=31,
        font_size=10,
    )
    primary.pack(fill="x", padx=12, pady=(0, 6))
    app.flash_button = primary
    app.series_button = primary
    app.series_stop_button = ctk.CTkButton(
        automatic, text="Serie beenden", command=app.stop_series, state="disabled"
    )
    app.series_stop_button.place_forget()

    def mode_changed(value: str) -> None:
        if value != "Serie":
            if getattr(app, "series_active", False) and not getattr(app, "busy", False):
                try:
                    app.stop_series()
                except Exception:
                    pass
            labels = {
                "Erstflash": "ERSTFLASH + PROFIL INSTALLIEREN",
                "Reparatur": "FIRMWARE REPARIEREN",
                "Werkseinstellung": "WERKSEINSTELLUNG STARTEN",
            }
            primary.configure(text=labels.get(value, "ERSTFLASH + PROFIL INSTALLIEREN"))
        else:
            primary.configure(text="SERIENMODUS STARTEN")

    mode_switch.configure(command=mode_changed)
    mode_changed(str(app.operation_mode.get()))

    # --------------------------------------------------------------- hints
    hint_text = (
        "• Erstflash installiert Firmware und das oben gewählte Funktionsprofil; ‚Nur Firmware updaten‘ erhält Profil/Namen/NVS.\n"
        "• Reparatur sichert und installiert vollständig; Werkseinstellung löscht erst nach Sicherheitsbackup lokale Einstellungen.\n"
        "• Der Vorabcheck sperrt falsche Boards, beschädigte Pakete und unsichere Partitionen.\n"
        "• Alte Profilversionen werden beim Speichern automatisch archiviert.\n"
        "• Bei USB-Fehlern folgen automatische Versuche mit sichereren Baudraten."
    )
    ctk.CTkLabel(
        hints,
        text=hint_text,
        anchor="nw",
        justify="left",
        font=_font(8),
        text_color=TEXT,
        wraplength=700,
    ).pack(fill="both", expand=True, padx=12, pady=(0, 6))

    # --------------------------------------------------------------- protocol
    protocol_top = ctk.CTkFrame(protocol, fg_color="transparent", height=27)
    protocol_top.pack(fill="x", padx=12, pady=(5, 3))
    ctk.CTkLabel(protocol_top, text="", image=icon("list", 13, TEXT), width=15).pack(
        side="left", padx=(0, 7)
    )
    ctk.CTkLabel(
        protocol_top, text="PROTOKOLL", font=_font(10, "bold"), text_color=TEXT
    ).pack(side="left")

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
                opener = shutil.which("xdg-open")
                if opener:
                    subprocess.Popen([opener, str(folder)])
        except Exception as exc:
            messagebox.showerror("Logordner", str(exc), parent=app)

    def create_support_zip() -> None:
        try:
            target = services.create_diagnostic_package(app=app)
            app._append_log(f"DIAGNOSE-ZIP · {target}")
            messagebox.showinfo(
                "Diagnose-ZIP erstellt",
                f"Das anonymisierte Diagnosepaket wurde gespeichert:\n\n{target}",
                parent=app,
            )
        except Exception as exc:
            app._show_error(exc)

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
            profile.grid_remove()
            identity.grid_remove()
            service.grid_remove()
            firmware.grid_remove()
            automatic.grid_remove()
            hints.grid_remove()
            body.grid_rowconfigure(1, minsize=0)
            body.grid_rowconfigure(2, minsize=0)
            body.grid_rowconfigure(3, minsize=0)
            toggle.configure(text="PROTOKOLL KOMPAKT")
        else:
            profile.grid()
            identity.grid()
            service.grid()
            firmware.grid()
            automatic.grid()
            hints.grid()
            body.grid_rowconfigure(1, minsize=ROW_INFO)
            body.grid_rowconfigure(2, minsize=ROW_SERVICE)
            body.grid_rowconfigure(3, minsize=ROW_ACTION)
            toggle.configure(text="PROTOKOLL GROSS")

    toggle = _button(
        protocol_top,
        "PROTOKOLL GROSS",
        toggle_protocol,
        icon_name="expand",
        height=24,
        font_size=8,
    )
    copy_btn = _button(
        protocol_top,
        "KOPIEREN",
        copy_protocol,
        icon_name="copy",
        height=24,
        font_size=8,
    )
    folder_btn = _button(
        protocol_top,
        "LOGORDNER",
        open_log_folder,
        icon_name="folder",
        height=24,
        font_size=8,
    )
    support_btn = _button(
        protocol_top,
        "DIAGNOSE-ZIP",
        create_support_zip,
        icon_name="file",
        height=24,
        font_size=8,
    )
    app.support_zip_button = support_btn
    clear_btn = _button(
        protocol_top,
        "PROTOKOLL LEEREN",
        clear_protocol,
        icon_name="trash",
        height=24,
        font_size=8,
    )
    clear_btn.pack(side="right")
    support_btn.pack(side="right", padx=(0, 6))
    folder_btn.pack(side="right", padx=(0, 6))
    copy_btn.pack(side="right", padx=(0, 6))
    toggle.pack(side="right", padx=(0, 6))

    app.log_box = ctk.CTkTextbox(
        protocol,
        corner_radius=6,
        fg_color="#05101B",
        border_width=0,
        font=_font(8, family="Consolas"),
    )
    app.log_box.pack(fill="both", expand=True, padx=12, pady=(0, 6))
    app.log_box.configure(state="disabled")

    # --------------------------------------------------------------- footer
    footer = ctk.CTkFrame(app, fg_color="transparent", height=18)
    footer.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 3))
    ctk.CTkLabel(
        footer,
        text=f"JARNSEN MESH Flasher   ·   {APP_VERSION}",
        font=_font(8),
        text_color=MUTED,
    ).pack(side="left")
    ctk.CTkLabel(
        footer, text="© 2026 JARNSEN   |", font=_font(8), text_color=MUTED
    ).pack(side="right", padx=(0, 7))
    ctk.CTkLabel(
        footer,
        textvariable=app.native_ready_var,
        font=_font(8, "bold"),
        text_color=TEXT,
    ).pack(side="right", padx=(0, 7))
    _dot(footer, "#22C55E", 7).pack(side="right", padx=(0, 5))

    # --------------------------------------------------------------- state wiring
    def refresh_counts() -> None:
        try:
            devices = list(getattr(app, "devices", []) or [])
            boards = sum(1 for item in devices if getattr(item, "board_key", None))
            ports = ", ".join(str(getattr(item, "port", "")) for item in devices[:3])
            more = f" +{len(devices) - 3}" if len(devices) > 3 else ""
            device_text = f"{len(devices)} Gerät(e)"
            if ports:
                device_text += f" · {ports}{more}"
            app.native_device_count_var.set(device_text)
            unknown = len(devices) - boards
            board_text = f"{boards} Board(s) bereit"
            if unknown:
                board_text += f" · {unknown} ungeklärt"
            app.native_board_count_var.set(board_text)
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
            app.available_firmware_var.set(
                f"Verfügbar: {local.display_name} · PC-Datei"
            )
            app.firmware_compare_var.set("PC-DATEI AUSGEWÄHLT")
            return

        app.available_firmware_var.set("Verfügbar: GitHub wird geprüft …")

        def worker() -> None:
            try:
                identity_value = query_jarnsen_identity(device_info.port) or fallback
                available = latest_available(services, board_key, force=force)
                state, detail = comparison_text(identity_value, available)

                def update() -> None:
                    if token != generation["value"]:
                        return
                    app.installed_firmware_var.set(
                        f"Installiert: {_installed_display(identity_value)}"
                    )
                    app.available_firmware_var.set(
                        f"Verfügbar: JARNSEN-MESH v{available.version} · Build {available.build}"
                    )
                    app.firmware_compare_var.set(f"{state} · {detail}")
                    app._append_log(
                        f"FIRMWARE STATUS · Port={device_info.port} · Installiert={_installed_display(identity_value)} · Verfügbar=JARNSEN-MESH v{available.version} Build {available.build} · Status={state}"
                    )

                app.after(0, update)
            except Exception as exc:
                error_message = str(exc)

                def fail() -> None:
                    if token != generation["value"]:
                        return
                    app.available_firmware_var.set(
                        "Verfügbar: GitHub-Prüfung fehlgeschlagen"
                    )
                    app.firmware_compare_var.set(error_message)

                app.after(0, fail)

        threading.Thread(
            target=worker, name="jarnsen-reference-fw-status", daemon=True
        ).start()

    app.refresh_firmware_status = refresh_firmware_status

    def refresh_firmware_labels(*_args: Any) -> None:
        installed_raw = str(app.installed_firmware_var.get() or "")
        available_raw = str(app.available_firmware_var.get() or "")
        compare = str(app.firmware_compare_var.get() or "").strip()
        installed_value.set(
            installed_raw.removeprefix("Installiert:").strip() or "wird gelesen"
        )
        available_value.set(
            available_raw.removeprefix("Verfügbar:").strip() or "noch nicht geprüft"
        )
        app.native_firmware_summary_var.set(
            f"Aktuell: {installed_value.get()}   |   Neueste: {available_value.get()}"
        )
        upper = compare.upper()
        if upper.startswith("AKTUELL"):
            firmware_badge.configure(text="AKTUELL", fg_color=GREEN)
            fw_small_badge.configure(text="Aktuell", fg_color=GREEN, image=None)
            status.configure(border_color="#22C55E")
        elif (
            upper.startswith("UPDATE VERFÜGBAR")
            or upper.startswith("ANDERE FIRMWARE")
            or upper.startswith("JARNSEN-MESH VERFÜGBAR")
        ):
            firmware_badge.configure(text="UPDATE EMPFOHLEN", fg_color=ORANGE)
            fw_small_badge.configure(
                text="Update verfügbar",
                fg_color="#9A4D00",
                image=icon("alert", 10, "#FBBF24"),
                compound="left",
            )
            status.configure(border_color="#F59E0B")
        elif upper.startswith("PC-DATEI"):
            firmware_badge.configure(text="PC-DATEI", fg_color=BLUE)
            fw_small_badge.configure(text="PC-Datei", fg_color=BLUE, image=None)
            status.configure(border_color="#3B82F6")
        elif upper.startswith("NEUER ALS GITHUB"):
            firmware_badge.configure(text="NODE NEUER", fg_color="#1E4E79")
            fw_small_badge.configure(text="Node neuer", fg_color="#1E4E79", image=None)
            status.configure(border_color="#60A5FA")
        else:
            firmware_badge.configure(text="WIRD GEPRÜFT", fg_color="#374151")
            fw_small_badge.configure(
                text="Wird geprüft", fg_color="#374151", image=None
            )
            status.configure(border_color="#475569")

    for var in (
        app.installed_firmware_var,
        app.available_firmware_var,
        app.firmware_compare_var,
    ):
        var.trace_add("write", refresh_firmware_labels)
    refresh_firmware_labels()

    def queue_fw_refresh(*_args: Any) -> None:
        app.after(220, refresh_firmware_status)

    app.device_var.trace_add("write", queue_fw_refresh)
    app.board_var.trace_add("write", queue_fw_refresh)

    original_set_progress = app._set_progress

    def progress_text(fraction: float) -> str:
        percent = int(round(max(0.0, min(1.0, float(fraction))) * 100))
        started = getattr(app, "_jarnsen_flash_started_at", None)
        if started is not None and getattr(app, "busy", False):
            elapsed = max(0, int(time.monotonic() - float(started)))
        else:
            elapsed = max(0, int(getattr(app, "_jarnsen_flash_elapsed", 0) or 0))
        if started is None and elapsed == 0:
            return f"{percent}%"
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        clock = (
            f"{hours:d}:{minutes:02d}:{seconds:02d}"
            if hours
            else f"{minutes:02d}:{seconds:02d}"
        )
        return f"{percent}% ({clock})"

    def native_set_progress(value: float, text: str) -> None:
        original_set_progress(value, text)
        fraction = max(0.0, min(1.0, float(value)))
        progress_pct.set(progress_text(fraction))
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
            for idx, (dot_label, text_label) in enumerate(stage_widgets):
                if idx < active:
                    color = "#22C55E"
                    name = "radio_on"
                elif idx == active:
                    color = "#3B9CFF"
                    name = "radio_on"
                else:
                    color = "#6F8498"
                    name = "radio_off"
                dot_label.configure(image=icon(name, 9, color))
                text_label.configure(
                    text_color="#C4D0DC" if idx <= active else "#8999A9"
                )

        app.after(0, update_stage)

    app._set_progress = native_set_progress

    original_set_busy = app._set_busy

    def native_set_busy(busy: bool) -> None:
        was_busy = bool(getattr(app, "busy", False))
        if busy and not was_busy:
            app._jarnsen_flash_started_at = time.monotonic()
            app._jarnsen_flash_elapsed = 0
        elif not busy and was_busy:
            started = getattr(app, "_jarnsen_flash_started_at", None)
            if started is not None:
                app._jarnsen_flash_elapsed = max(
                    0, int(time.monotonic() - float(started))
                )
        original_set_busy(busy)
        state = "disabled" if busy else "normal"
        app.native_ready_var.set("Arbeitet …" if busy else "Bereit")
        for btn in native_busy_buttons:
            try:
                btn.configure(state=state)
            except Exception:
                pass

    app._set_busy = native_set_busy

    def refresh_elapsed() -> None:
        try:
            if getattr(app, "busy", False):
                progress_pct.set(progress_text(float(app.progress.get())))
            app.after(1000, refresh_elapsed)
        except Exception:
            pass

    app.after(1000, refresh_elapsed)

    refresh_counts()
    refresh_profile_line()
    app.after(420, refresh_firmware_status)
    try:
        app._append_log(
            "UI · Referenzoberfläche v2 · Single-Pass · feste PIL-Icons · 1920x1080@125%"
        )
    except Exception:
        pass
    _emit(
        "REFERENCE DASHBOARD ready architecture=single-pass icons=pil layout=1920x1080@125"
    )
