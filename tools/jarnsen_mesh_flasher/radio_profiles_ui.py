from __future__ import annotations

from pathlib import Path
from typing import Any

import customtkinter as ctk
import yaml

import radio_profiles


BG_INNER = "#091522"
BORDER = "#2A4057"
CONTROL = "#15273A"
CONTROL_HOVER = "#1D354D"
TEXT = "#EAF0F7"
MUTED = "#93A6BA"
GREEN = "#86EFAC"
WARN = "#FBBF24"
FONT = "Segoe UI"


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


def _find_profile_card(app: Any) -> Any | None:
    body = getattr(app, "body", None)
    if body is None:
        return None
    try:
        candidates = list(body.winfo_children())
    except Exception:
        return None
    for candidate in candidates:
        for child in _walk(candidate):
            if not isinstance(child, ctk.CTkLabel):
                continue
            try:
                text = str(child.cget("text") or "").strip()
            except Exception:
                continue
            if text == "2. GRUNDEINSTELLUNGEN":
                return candidate
    return None


def _font(size: int, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT, size=size, weight=weight)


def _profile_region(app: Any) -> str:
    raw = ""
    try:
        raw = str(app.profile_path_var.get() or "").strip()
    except Exception:
        pass
    if not raw or raw == "Kein Profil geladen":
        return ""
    try:
        path = Path(raw)
        if not path.exists():
            return ""
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
        if not isinstance(data, dict):
            return ""
        config = data.get("config")
        if isinstance(config, dict) and isinstance(config.get("lora"), dict):
            return str(config["lora"].get("region") or "").strip()
        if isinstance(data.get("lora"), dict):
            return str(data["lora"].get("region") or "").strip()
    except Exception:
        pass
    return ""


def _attach_radio_controls(app: Any, services: Any) -> None:
    if getattr(app, "_jarnsen_radio_profile_ui_ready", False):
        return
    profile = _find_profile_card(app)
    if profile is None:
        _emit("RADIO PROFILE UI skipped profile-card-not-found=1")
        return

    app._jarnsen_radio_profile_ui_ready = True
    try:
        # One compact dynamic editor is used instead of three permanently visible
        # panels. Every JARNSEN frequency profile remembers its own hops + modem.
        app.body.grid_rowconfigure(1, minsize=204)
    except Exception:
        pass

    settings_state = radio_profiles.load_settings(services)
    app.radio_profile_var = ctk.StringVar(
        value=radio_profiles.PROFILE_LABELS.get(settings_state.get("selected"), "Standard")
    )
    app.radio_hop_var = ctk.StringVar(value=str(radio_profiles.hop_limit_for(settings_state)))
    app.radio_modem_var = ctk.StringVar(value="Profil/FW")
    app.radio_frequency_var = ctk.StringVar(value="")
    app.radio_tx_var = ctk.StringVar(value="")
    app.radio_duty_var = ctk.StringVar(value="")
    app.radio_profile_status_var = ctk.StringVar(value=radio_profiles.summary(settings_state))
    app.radio_profile_allocation_var = ctk.StringVar(value="Region: aus geladenem Profil")

    radio = ctk.CTkFrame(
        profile,
        fg_color=BG_INNER,
        corner_radius=6,
        border_width=1,
        border_color=BORDER,
        height=68,
    )
    radio.pack(fill="x", padx=12, pady=(0, 6))
    for col in (1, 3, 5, 7, 9, 11):
        radio.grid_columnconfigure(col, weight=0)
    radio.grid_columnconfigure(12, weight=1)

    app.radio_profile_panel = radio
    app.radio_profile_card = profile

    ctk.CTkLabel(radio, text="Funkprofil", font=_font(8, "bold"), text_color=MUTED).grid(
        row=0, column=0, sticky="w", padx=(8, 5), pady=(5, 2)
    )
    profile_menu = ctk.CTkOptionMenu(
        radio,
        variable=app.radio_profile_var,
        values=["Standard", "Jarnsen 1", "Jarnsen 2"],
        width=112,
        height=25,
        corner_radius=5,
        fg_color=CONTROL,
        button_color=CONTROL_HOVER,
        button_hover_color="#29445E",
        font=_font(9),
        dropdown_font=_font(9),
    )
    profile_menu.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=(5, 2))

    ctk.CTkLabel(radio, text="Frequenz", font=_font(8), text_color=MUTED).grid(
        row=0, column=2, sticky="e", padx=(0, 4), pady=(5, 2)
    )
    ctk.CTkLabel(
        radio,
        textvariable=app.radio_frequency_var,
        width=88,
        anchor="w",
        font=_font(9, "bold"),
        text_color=TEXT,
    ).grid(row=0, column=3, sticky="w", padx=(0, 8), pady=(5, 2))

    ctk.CTkLabel(radio, text="Modem", font=_font(8), text_color=MUTED).grid(
        row=0, column=4, sticky="e", padx=(0, 4), pady=(5, 2)
    )
    modem_menu = ctk.CTkOptionMenu(
        radio,
        variable=app.radio_modem_var,
        values=["Profil/FW"],
        width=116,
        height=25,
        corner_radius=5,
        fg_color=CONTROL,
        button_color=CONTROL_HOVER,
        button_hover_color="#29445E",
        font=_font(9),
        dropdown_font=_font(9),
    )
    modem_menu.grid(row=0, column=5, sticky="w", padx=(0, 8), pady=(5, 2))

    ctk.CTkLabel(radio, text="Hops", font=_font(8), text_color=MUTED).grid(
        row=0, column=6, sticky="e", padx=(0, 4), pady=(5, 2)
    )
    hop_menu = ctk.CTkOptionMenu(
        radio,
        variable=app.radio_hop_var,
        values=radio_profiles.hop_values(settings_state.get("selected", radio_profiles.PROFILE_STANDARD)),
        width=58,
        height=25,
        corner_radius=5,
        fg_color=CONTROL,
        button_color=CONTROL_HOVER,
        button_hover_color="#29445E",
        font=_font(9),
        dropdown_font=_font(9),
    )
    hop_menu.grid(row=0, column=7, sticky="w", padx=(0, 8), pady=(5, 2))

    ctk.CTkLabel(radio, text="TX", font=_font(8), text_color=MUTED).grid(
        row=0, column=8, sticky="e", padx=(0, 4), pady=(5, 2)
    )
    ctk.CTkLabel(
        radio,
        textvariable=app.radio_tx_var,
        width=68,
        anchor="w",
        font=_font(9, "bold"),
        text_color=TEXT,
    ).grid(row=0, column=9, sticky="w", padx=(0, 8), pady=(5, 2))

    ctk.CTkLabel(radio, text="Duty", font=_font(8), text_color=MUTED).grid(
        row=0, column=10, sticky="e", padx=(0, 4), pady=(5, 2)
    )
    ctk.CTkLabel(
        radio,
        textvariable=app.radio_duty_var,
        width=72,
        anchor="w",
        font=_font(9, "bold"),
        text_color=TEXT,
    ).grid(row=0, column=11, sticky="w", padx=(0, 8), pady=(5, 2))

    status_label = ctk.CTkLabel(
        radio,
        textvariable=app.radio_profile_status_var,
        anchor="w",
        justify="left",
        font=_font(8, "bold"),
        text_color=GREEN,
    )
    status_label.grid(row=1, column=0, columnspan=9, sticky="ew", padx=(8, 8), pady=(1, 5))

    allocation_label = ctk.CTkLabel(
        radio,
        textvariable=app.radio_profile_allocation_var,
        anchor="e",
        font=_font(8),
        text_color=MUTED,
    )
    allocation_label.grid(row=1, column=9, columnspan=4, sticky="e", padx=(8, 8), pady=(1, 5))

    app.radio_profile_menu = profile_menu
    app.radio_modem_menu = modem_menu
    app.radio_hop_menu = hop_menu

    def selected_key() -> str:
        return radio_profiles.PROFILE_KEYS_BY_LABEL.get(
            str(app.radio_profile_var.get()),
            radio_profiles.PROFILE_STANDARD,
        )

    def refresh_allocation(*_args: Any) -> None:
        region = _profile_region(app)
        key = selected_key()
        if not region:
            app.radio_profile_allocation_var.set("Region: aus geladenem Profil")
            allocation_label.configure(text_color=MUTED)
            return

        frequency = radio_profiles.profile_frequency(key)
        if frequency is None:
            app.radio_profile_allocation_var.set(f"Region: {radio_profiles.allocation_summary(region)}")
            allocation_label.configure(text_color=MUTED)
            return

        try:
            radio_profiles.validate_frequency_for_region(
                frequency,
                region,
                label=radio_profiles.PROFILE_LABELS[key],
            )
            app.radio_profile_allocation_var.set(f"Region: {radio_profiles.allocation_summary(region)}")
            allocation_label.configure(text_color=MUTED)
        except Exception:
            app.radio_profile_allocation_var.set(
                f"Region {region} passt nicht zu {float(frequency):.3f} MHz"
            )
            allocation_label.configure(text_color=WARN)

    def refresh_active_controls() -> None:
        nonlocal settings_state
        key = selected_key()
        checked = radio_profiles.validate_settings(settings_state)
        frequency = radio_profiles.profile_frequency(key)
        if frequency is None:
            app.radio_frequency_var.set("Profil/FW")
            app.radio_tx_var.set("Profil/FW")
            app.radio_duty_var.set("Profil/FW")
            app.radio_modem_var.set("Profil/FW")
            modem_menu.configure(values=["Profil/FW"], state="disabled")
        else:
            app.radio_frequency_var.set(f"{float(frequency):.3f} MHz")
            app.radio_tx_var.set("Max/Auto")
            app.radio_duty_var.set("Frei")
            modem = radio_profiles.modem_preset_for(checked, key) or "LONG_FAST"
            app.radio_modem_var.set(radio_profiles.MODEM_LABELS.get(modem, modem))
            modem_menu.configure(values=radio_profiles.modem_preset_values(), state="normal")

        hop_menu.configure(values=radio_profiles.hop_values(key))
        app.radio_hop_var.set(str(radio_profiles.hop_limit_for(checked, key)))
        app.radio_profile_status_var.set(radio_profiles.summary(checked))
        status_label.configure(text_color=GREEN)
        refresh_allocation()

    def persist_selected(_value: str | None = None) -> None:
        nonlocal settings_state
        key = selected_key()
        settings_state["selected"] = key
        settings_state = radio_profiles.save_settings(settings_state, services)
        refresh_active_controls()

    def persist_modem(value: str | None = None) -> None:
        nonlocal settings_state
        key = selected_key()
        setting_key = radio_profiles.MODEM_SETTING_KEYS.get(key)
        if setting_key is None:
            refresh_active_controls()
            return
        canonical = radio_profiles.MODEM_KEYS_BY_LABEL.get(
            str(value or app.radio_modem_var.get()),
            "LONG_FAST",
        )
        settings_state["selected"] = key
        settings_state[setting_key] = canonical
        settings_state = radio_profiles.save_settings(settings_state, services)
        refresh_active_controls()

    def persist_hops(_value: str | None = None) -> None:
        nonlocal settings_state
        key = selected_key()
        hop_key = radio_profiles.HOP_KEYS[key]
        settings_state["selected"] = key
        settings_state[hop_key] = app.radio_hop_var.get()
        settings_state = radio_profiles.save_settings(settings_state, services)
        refresh_active_controls()

    profile_menu.configure(command=persist_selected)
    modem_menu.configure(command=persist_modem)
    hop_menu.configure(command=persist_hops)

    try:
        app.profile_path_var.trace_add("write", refresh_allocation)
    except Exception:
        pass

    try:
        refresh_active_controls()
    except Exception as exc:
        app.radio_profile_status_var.set(str(exc))
        status_label.configure(text_color=WARN)
        refresh_allocation()

    _emit(
        "RADIO PROFILE UI ready dynamic-editor=1 dropdown-profile=1 dropdown-modem=1 dropdown-hops=1 "
        "fixed-j1=915.625 fixed-j2=917.375 separate-hop-state=1 separate-modem-state=1 "
        "tx-duty-status=1 persistent=1 "
        f"selected={settings_state.get('selected')} standard-hops={settings_state.get('standard_hops')} "
        f"j1-hops={settings_state.get('jarnsen_1_hops')} j2-hops={settings_state.get('jarnsen_2_hops')} "
        f"j1-modem={settings_state.get('jarnsen_1_modem_preset')} "
        f"j2-modem={settings_state.get('jarnsen_2_modem_preset')}"
    )


def install(services: Any) -> None:
    if getattr(services, "_jarnsen_radio_profiles_ui_installed", False):
        return
    services._jarnsen_radio_profiles_ui_installed = True

    import reference_dashboard

    original = reference_dashboard._build_dashboard
    if getattr(original, "_jarnsen_radio_profile_wrapper", False):
        return

    def build_dashboard(app: Any, runtime_services: Any) -> None:
        original(app, runtime_services)
        _attach_radio_controls(app, runtime_services)

    build_dashboard._jarnsen_radio_profile_wrapper = True  # type: ignore[attr-defined]
    reference_dashboard._build_dashboard = build_dashboard
    _emit("RADIO PROFILE UI installed active-dashboard-wrapper=1")
